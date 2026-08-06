/* gwt-app.js - the workspace: navigation, state and every page.
 *
 * One project lives in the store at a time, and the pages follow the lifecycle
 * of a real borehole: site the well, design it, drill it, test it, sample it,
 * cost it, supervise it, hand it over. Each page ends with a route to the next
 * step so a field team is never left wondering what to do with a result.
 *
 * Nothing leaves the browser. Uploaded sheets are parsed in the page, results
 * are held in memory and mirrored to localStorage, and the project file the
 * user downloads is the only copy that persists.
 */
(function (global) {
  'use strict';

  var GWT = global.GWT || (global.GWT = {});
  var S = GWT.support, C = GWT.core, charts = GWT.charts, docx = GWT.docx;
  var el = S.el, $ = S.$, card = S.card, button = S.button, field = S.field;

  var STORE_KEY = 'gwt.project.v1';

  var NAV_GROUPS = [
    ['Project', [
      ['overview', 'Overview'],
      ['guided', 'Guided start'],
      ['site', 'Site & maps'],
    ]],
    ['Investigation', [
      ['ves', 'Geophysics (VES)'],
      ['design', 'Borehole design'],
      ['spine', 'Depth Spine'],
      ['extract', 'Scanned sheets'],
    ]],
    ['Testing', [
      ['pumping', 'Pumping test'],
      ['quality', 'Water quality'],
    ]],
    ['Delivery', [
      ['costing', 'Costing & BoQ'],
      ['supervision', 'Supervision'],
      ['handover', 'Handover'],
      ['templates', 'Templates'],
    ]],
    ['Area analysis', [
      ['waterpoints', 'Water points'],
      ['coverage', 'Coverage gap'],
      ['portfolio', 'Portfolio'],
      ['registry', 'Asset registry'],
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
      supervision: { responses: {}, notes: [], checks: {} },
      handover: { committee: [], notes: [], date: '' },
      photos: {},
      coverage: { level: 'district' },
      waterpoints: { radius: 1000 },
      spine: { stage: 'design', ledger: {}, signatory: '' },
      extraction: { model: '' },
      /* per report kind: { requirementKey: {reason, by} } */
      overrides: {},
      asset: null,
      seasonal: {},
      theme: 'auto',
    };
  }

  /* Autosave is a mirror of the session into localStorage, and it is the only
   * thing standing between a browser refresh and a lost day of fieldwork. It
   * fails silently by design - quota is finite and photos are large - so the
   * failure has to be said out loud, and it has to keep being said until the
   * user has a project file on disk. */
  function renderAutosaveBanner(broken) {
    var host = document.getElementById('autosave-banner');
    if (!host) return;
    S.clear(host);
    if (!broken) return;
    S.append(host, el('div.callout.callout-bad', [
      el('p', el('strong', 'Autosave has stopped')),
      el('p', 'This browser will not keep a copy of the session any more — ' +
        'usually because its storage is full, often from photographs. If you ' +
        'refresh or close this tab, unsaved work is gone. Save a project file ' +
        'now; it is the only record from here on.'),
      button('Save project', saveProject),
    ]));
  }

  var store = S.createStore(blankState(), {
    persistKey: STORE_KEY,
    onPersistError: function () {
      renderAutosaveBanner(true);
      S.toast('Autosave has stopped — save a project file now.', 'error', 12000);
    },
    onPersistRecovered: function () {
      renderAutosaveBanner(false);
      S.toast('Autosave is working again.', 'ok');
    },
  });

  /* The API key is deliberately NOT part of the persisted state.
   *
   * It used to be, and the store mirrors the whole state into localStorage on
   * every change - so the key sat unencrypted on disk, survived closing the
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
   * one thing a report must never contain. */
  var derived = {
    soundings: null, inversions: null, interpretations: null,
    log: null, test: null, analysis: null, sample: null, assessment: null,
    design: null, estimate: null, programme: null,
    /* brought in by hand rather than computed from the sources: an area
     * inventory, other projects' summaries, an extracted scan */
    waterPoints: null, waterPointsSource: null, waterPointsCapped: false,
    portfolio: null, extraction: null,
  };

  /* ------------------------------------------------------------------ chrome */

  function siteLabel() {
    var site = store.get('site');
    return site.community || site.project || site.client || 'Untitled project';
  }

  function renderChrome() {
    var site = store.get('site');
    var chip = $('#site-chip');
    S.clear(chip);
    var meta = [site.district, site.client].filter(Boolean).join(' · ');
    S.append(chip, [
      el('span.site-chip-name', siteLabel()),
      el('span.site-chip-meta', meta ||
        'Load a sample or upload a field sheet to begin'),
    ]);

    var actions = $('#top-actions');
    S.clear(actions);
    S.append(actions, [
      button('Save project', saveProject, { variant: 'ghost',
        title: 'Download the whole working session as a .gwt file' }),
      button('Open project', openProject, { variant: 'ghost' }),
      button(themeIcon(), toggleTheme, { variant: 'ghost', title: 'Switch theme' }),
    ]);
    renderNav();
  }

  function themeIcon() {
    var theme = store.get('theme', 'auto');
    return theme === 'dark' ? '☾' : (theme === 'light' ? '☀' : '◐');
  }

  function toggleTheme() {
    var order = ['auto', 'light', 'dark'];
    var next = order[(order.indexOf(store.get('theme', 'auto')) + 1) % order.length];
    store.set('theme', next);
    applyTheme();
    renderChrome();
    render();
  }

  function applyTheme() {
    var theme = store.get('theme', 'auto');
    if (theme === 'auto') document.documentElement.removeAttribute('data-theme');
    else document.documentElement.setAttribute('data-theme', theme);
  }

  /* A dot per page shows what is done, so the next thing to do is visible from
   * anywhere in the workspace. */
  function pageDone(key) {
    switch (key) {
      case 'site': return !!store.get('site.community');
      case 'ves': return !!(derived.interpretations && derived.interpretations.length);
      case 'design': return !!derived.design;
      case 'pumping': return !!derived.analysis;
      case 'quality': return !!derived.assessment;
      case 'costing': return !!derived.estimate;
      case 'supervision': return Object.keys(store.get('supervision.responses') || {}).length > 0;
      case 'handover': return !!(derived.design && derived.analysis);
      default: return false;
    }
  }

  function renderNav() {
    var nav = $('#app-nav');
    S.clear(nav);
    var current = store.get('nav');
    NAV_GROUPS.forEach(function (group) {
      var items = group[1].map(function (page) {
        var key = page[0];
        return el('button.nav-item' + (key === current ? '.active' : '') +
          (pageDone(key) ? '.done' : ''), {
          type: 'button',
          onclick: function () { goto(key); },
          'aria-current': key === current ? 'page' : null,
        }, [el('span.nav-dot'), el('span', page[1])]);
      });
      S.append(nav, el('div.nav-group', [
        group[0] ? el('div.nav-group-title', group[0]) : null,
        el('div', items),
      ]));
    });
  }

  function goto(key) {
    store.set('nav', key);
    render();
    $('#app-nav').classList.remove('open');
    $('#main').focus({ preventScroll: true });
    global.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function nextStep(note, label, page) {
    return el('div.next-step', [
      el('p.next-note', note),
      button(label + ' →', function () { goto(page); }),
    ]);
  }

  function pageHead(title, lead, crumb) {
    return el('div.page-head', [
      crumb ? el('div.crumb', crumb) : null,
      el('h1', title),
      lead ? el('p.lead', lead) : null,
    ]);
  }

  /* Shown wherever a national verdict is put in front of the user, for as long
   * as any national value in the standards table is still unconfirmed. Failing
   * an unconfirmed limit is a prompt to check the specification, not a
   * compliance finding - and the difference matters to whoever signs. */
  function provisionalStandardsNote() {
    var params = C.provisionalNationalParameters();
    if (!params.length) return null;
    return el('div.callout.callout-warn', [
      el('p', el('strong', 'National limits are provisional')),
      el('p', C.PROVISIONAL_NATIONAL_NOTE),
      el('p.muted', 'Unconfirmed: ' + params.join(', ') + '.'),
    ]);
  }

  /* ------------------------------------------------------------- computation */

  function config() {
    return C.withConfig(store.get('config'));
  }

  /* Rebuild every derived result from the stored sources. Called after any
   * upload, any manual entry and on load, so what a page shows and what a
   * report contains are always the same computation. */
  async function recompute() {
    recomputeState.running += 1;
    try {
      await recomputeInner();
    } finally {
      recomputeState.running -= 1;
      recomputeState.generation += 1;
    }
  }

  var recomputeState = { running: 0, generation: 0 };

  async function recomputeInner() {
    var sources = store.get('sources') || {};
    var cfg = config();

    derived.soundings = null; derived.inversions = null;
    derived.interpretations = null;
    if (sources.ves) {
      try {
        var sheets = await S.readXlsx(S.base64ToBytes(sources.ves.b64));
        derived.soundings = C.readVesSheets(sheets, sources.ves.name);
      } catch (e) {
        S.toast('VES sheet: ' + e.message, 'error');
      }
    }

    derived.log = null;
    if (sources.drilling) {
      try {
        var dsheets = await S.readXlsx(S.base64ToBytes(sources.drilling.b64));
        derived.log = C.drillingFromGrid(dsheets[0].rows, sources.drilling.name);
      } catch (e2) {
        S.toast('Drilling log: ' + e2.message, 'error');
      }
    }

    derived.test = null; derived.analysis = null;
    if (sources.pumping) {
      try {
        var pbytes = S.base64ToBytes(sources.pumping.b64);
        /* the crew is handed a Word field sheet as often as the workbook;
         * refusing it is how readings get retyped, and retyping is where the
         * transcription errors come from */
        if (/\.docx$/i.test(sources.pumping.name || '')) {
          derived.test = await C.readPumpingDocx(pbytes, sources.pumping.name);
        } else {
          var psheets = await S.readXlsx(pbytes);
          derived.test = C.pumpingFromGrid(psheets[0].rows, sources.pumping.name);
        }
        applyManualDischarges(derived.test);
        derived.analysis = C.analysePumpingTest(derived.test, cfg);
      } catch (e3) {
        S.toast('Pumping sheet: ' + e3.message, 'error');
      }
    }

    derived.sample = null; derived.assessment = null;
    if (sources.quality) {
      try {
        var qsheets = await S.readXlsx(S.base64ToBytes(sources.quality.b64));
        derived.sample = C.qualityFromGrid(qsheets[0].rows, sources.quality.name);
        derived.assessment = C.assessSample(derived.sample);
      } catch (e4) {
        S.toast('Water quality sheet: ' + e4.message, 'error');
      }
    }

    adoptSiteMetadata();
    rebuildDesign();
    rebuildCosting();
  }

  /* The crew often writes discharge nowhere on the sheet; the value entered on
   * the Pumping test page belongs to the project, not to the file. */
  function applyManualDischarges(test) {
    var manual = store.get('pumping.manualDischarges') || {};
    (test.steps || []).forEach(function (step) {
      var value = manual[step.step_number];
      if (value !== undefined && value !== null && value !== '') {
        step.discharge_m3_per_h = Number(value);
      }
    });
  }

  /* The first sheet that carries a header block seeds the project metadata,
   * and later sheets only fill blanks - a typo in one sheet must not overwrite
   * a value the analyst has already corrected. */
  function adoptSiteMetadata() {
    var site = store.get('site');
    var candidates = [derived.log, derived.test, derived.sample]
      .concat(derived.soundings || [])
      .filter(Boolean).map(function (o) { return o.site; }).filter(Boolean);
    var changed = false;
    candidates.forEach(function (source) {
      Object.keys(site).forEach(function (key) {
        var value = source[key];
        var empty = site[key] === '' || site[key] === null || site[key] === undefined;
        if (empty && value !== '' && value !== null && value !== undefined) {
          site[key] = value; changed = true;
        }
      });
    });
    if (changed) store.set('site', site);
  }

  function rebuildDesign() {
    derived.design = null;
    var cfg = config();
    var interp = bestInterpretation();
    var swl = derived.test ? derived.test.static_water_level_m : null;
    var custom = store.get('design') || {};
    var totalDepth = custom.totalDepth;
    if (!totalDepth && derived.log && derived.log.total_depth_m) {
      totalDepth = derived.log.total_depth_m;
    }
    if (!totalDepth && interp) totalDepth = interp.max_drilling_depth_m;
    if (!totalDepth) return;
    try {
      derived.design = C.designBorehole({
        log: derived.log, interpretation: interp,
        staticWaterLevelM: swl === undefined ? null : swl,
        pumpIntakeM: custom.pumpIntake !== null && custom.pumpIntake !== undefined
          ? custom.pumpIntake
          : (derived.analysis && derived.analysis.yield_recommendation
            ? derived.analysis.yield_recommendation.pump_installation_depth_m : null),
        rules: cfg.design, totalDepthM: totalDepth,
        screensM: custom.screens && custom.screens.length ? custom.screens : null,
      });
    } catch (e) {
      S.toast('Borehole design: ' + e.message, 'warn');
    }
  }

  function rebuildCosting() {
    derived.estimate = null; derived.programme = null;
    var costing = store.get('costing');
    var inputs;
    if (derived.design) {
      inputs = C.inputsFromDesign(derived.design, {
        mobilisationDistanceKm: costing.mobilisation_km,
        overburdenM: overburdenFromData(),
      });
    } else if (costing.total_depth_m) {
      inputs = C.costingInputs({
        total_depth_m: costing.total_depth_m,
        mobilisation_distance_km: costing.mobilisation_km,
      });
    } else {
      return;
    }
    inputs.wq_samples = costing.wq_samples;
    inputs.handpumps = costing.handpumps;

    var rates = C.loadRates().map(function (rate) {
      var override = (costing.rateOverrides || {})[rate.code];
      return override === undefined || override === null || override === ''
        ? rate : Object.assign({}, rate, { unit_cost_usd: Number(override) });
    });
    try {
      derived.estimate = C.estimateBoreholeCost(inputs, rates, {
        overheadsPercent: costing.overheads, marginPercent: costing.margin,
        contingencyPercent: costing.contingency, vatPercent: costing.vat,
        exchangeRate: costing.exchange,
      });
      if (costing.programme_n > 1) {
        derived.programme = C.estimateProgrammeCost(inputs, costing.programme_n, {
          rates: rates, successRatePercent: costing.success_rate,
          interSiteDistanceKm: costing.inter_site_km,
          overheadsPercent: costing.overheads, marginPercent: costing.margin,
          contingencyPercent: costing.contingency, vatPercent: costing.vat,
          exchangeRate: costing.exchange,
        });
      }
    } catch (e) {
      S.toast('Cost estimate: ' + e.message, 'warn');
    }
  }

  /* The weathered zone thickness the cost model wants: from the drilling log's
   * fresh-rock contact when there is one, else the VES depth to basement. */
  function overburdenFromData() {
    if (derived.log && derived.log.intervals && derived.log.intervals.length) {
      for (var i = 0; i < derived.log.intervals.length; i++) {
        if (/fresh|unweathered|competent/i.test(derived.log.intervals[i].description || '')) {
          return derived.log.intervals[i].top_m;
        }
      }
    }
    var interp = bestInterpretation();
    if (interp && interp.depth_to_basement_m !== null) return interp.depth_to_basement_m;
    return null;
  }

  function bestInterpretation() {
    if (!derived.interpretations || !derived.interpretations.length) return null;
    var ranked = derived.interpretations.slice().sort(function (a, b) {
      return (a.rank || 99) - (b.rank || 99);
    });
    return ranked[0];
  }

  /* --------------------------------------------------------------- project IO */

  /* A headline summary of the project, saved beside the state so a portfolio
   * can be built from many project files without recomputing each one. The
   * same keys the Streamlit app writes, so the two file formats meet on the
   * Portfolio page. */
  function projectSummary() {
    var site = store.get('site') || {};
    var summary = {
      community: site.community, district: site.district,
      chiefdom: site.chiefdom, easting: site.easting,
      northing: site.northing, utm_zone: site.utm_zone,
    };
    if (derived.log) {
      if (derived.log.status) summary.status = derived.log.status;
      if (derived.log.total_depth_m) summary.total_depth_m = derived.log.total_depth_m;
    }
    var rec = derived.analysis ? derived.analysis.yield_recommendation : null;
    if (rec && rec.safe_yield_m3_per_h) {
      summary.safe_yield_m3_per_h = rec.safe_yield_m3_per_h;
    }
    if (derived.assessment) {
      /* The full five-state verdict. The old three states folded a national
       * standard failure into "aesthetic" and had no way to say "we cannot
       * tell", so a breached or unevaluable supply read as merely a matter of
       * taste. The schema marker lets a reader tell a new file from an old
       * one and translate the old vocabulary safely. */
      summary.water_verdict = derived.assessment.verdict_state;
      summary.verdict_schema = C.VERDICT_SCHEMA;
    }
    if (derived.estimate) summary.cost_per_meter_usd = derived.estimate.cost_per_meter_usd;
    if (derived.interpretations && derived.interpretations.length && !summary.status) {
      summary.status = 'sited';
    }
    Object.keys(summary).forEach(function (key) {
      var value = summary[key];
      if (value === null || value === undefined || value === '') delete summary[key];
    });
    return summary;
  }

  function projectPayload() {
    /* A project file is meant to be mailed to a colleague, so the API key
     * never goes in it: a credential that travels with the fieldwork is a
     * credential that leaks. It is not in the store at all any more, and this
     * scrub stays as a second line of defence against a stale field. */
    var state = Object.assign({}, store.state);
    state.extraction = Object.assign({}, state.extraction || {});
    delete state.extraction.apiKey;
    return {
      format: 'groundwater-toolkit-project',
      version: 1,
      saved: new Date().toISOString(),
      summary: projectSummary(),
      state: state,
    };
  }

  function saveProject() {
    var name = S.slug(siteLabel()) + '.gwt.json';
    S.download(name, JSON.stringify(projectPayload(), null, 1), 'application/json');
    S.toast('Project saved as ' + name, 'ok');
  }

  async function openProject() {
    var file = await S.pickFile('.json,.gwt,application/json');
    if (!file) return;
    try {
      var payload = JSON.parse(await S.readFile(file, 'text'));
      var state = payload.state || payload;
      if (!state || typeof state !== 'object') throw new Error('not a project file');
      /* A hand-edited or old-build project file can carry a key; it must
       * never be adopted into this session's storage. The key held for this
       * tab is untouched - it belongs to this browser, not to the file. */
      if (state.extraction) delete state.extraction.apiKey;
      store.replace(Object.assign(blankState(), state));
      applyTheme();
      await recompute();
      await runInversions({ quiet: true });
      renderChrome();
      render();
      S.toast('Project loaded.', 'ok');
    } catch (e) {
      S.toast('That file is not a Groundwater Toolkit project: ' + e.message, 'error');
    }
  }

  async function loadSample(key) {
    var sample = (GWT.data.samples || {})[key];
    if (!sample) return;
    var fresh = blankState();
    fresh.nav = store.get('nav');
    fresh.theme = store.get('theme', 'auto');
    Object.keys(sample.site || {}).forEach(function (k) {
      fresh.site[k] = sample.site[k];
    });
    fresh.sources = {};
    Object.keys(sample.files).forEach(function (role) {
      fresh.sources[role === 'ipi2win' ? 'ipi2win' : role] = {
        name: sample.files[role].name, b64: sample.files[role].b64,
      };
    });
    store.replace(fresh);
    await recompute();
    await runInversions({ quiet: false });
    renderChrome();
    render();
    S.toast('Loaded ' + sample.label + '.', 'ok');
  }

  /* --------------------------------------------------------------- uploading */

  function uploadZone(role, label, hint, accept) {
    var sources = store.get('sources') || {};
    var loaded = sources[role];
    var zone = el('div.upload-zone' + (loaded ? '.loaded' : ''), {
      tabindex: '0', role: 'button',
      onclick: function () { pick(); },
      onkeydown: function (e) {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(); }
      },
    }, [
      el('strong', loaded ? loaded.name : label),
      el('span', loaded ? 'Loaded — click to replace' : (hint || 'Click or drop the file here')),
    ]);

    async function take(file) {
      if (!file) return;
      try {
        var buffer = await S.readFile(file);
        var bytes = new Uint8Array(buffer);
        store.set('sources.' + role, { name: file.name, b64: S.bytesToBase64(bytes) });
        await S.withBusy($('#page-host'), 'Reading ' + file.name + '…', async function () {
          await recompute();
          if (role === 'ves') await runInversions({ quiet: false });
        });
        render();
        S.toast(file.name + ' loaded.', 'ok');
      } catch (e) {
        S.toast('Could not read ' + file.name + ': ' + e.message, 'error');
      }
    }
    function pick() { S.pickFile(accept || '.xlsx,.xls').then(take); }

    zone.addEventListener('dragover', function (e) {
      e.preventDefault(); zone.classList.add('over');
    });
    zone.addEventListener('dragleave', function () { zone.classList.remove('over'); });
    zone.addEventListener('drop', function (e) {
      e.preventDefault(); zone.classList.remove('over');
      take((e.dataTransfer.files || [])[0]);
    });
    return el('div', [
      zone,
      loaded ? el('div.btn-row', { style: { marginTop: '0.5rem' } }, [
        button('Remove', async function () {
          store.remove('sources.' + role);
          await recompute();
          render();
        }, { variant: 'ghost' }),
      ]) : null,
    ]);
  }

  /* The VES inversion is the one expensive computation; it runs with a spinner
   * and a progress note rather than freezing the page. */
  async function runInversions(options) {
    var opts = options || {};
    if (!derived.soundings || !derived.soundings.length) {
      derived.inversions = null; derived.interpretations = null;
      return;
    }
    var cfg = config();
    var host = $('#page-host');
    var results = [], interpretations = [];
    var work = async function () {
      for (var i = 0; i < derived.soundings.length; i++) {
        var sounding = derived.soundings[i];
        await S.nextFrame();
        try {
          var result = C.invertSounding(sounding, { config: cfg });
          results.push(result);
          interpretations.push(C.interpretModel(sounding, result.model, cfg));
        } catch (e) {
          S.toast(sounding.sounding_id + ': ' + e.message, 'warn');
        }
      }
    };
    if (opts.quiet) await work();
    else {
      await S.withBusy(host, 'Inverting ' + derived.soundings.length + ' ' +
        S.plural(derived.soundings.length, 'sounding') + '…', work);
    }
    derived.inversions = results;
    derived.interpretations = interpretations;
    C.rankInterpretations(interpretations, store.get('ves.preferredOrder'));
    rebuildDesign();
    rebuildCosting();
  }

  /* ================================================================== pages */

  var PAGES = {};

  /* --- overview ------------------------------------------------------------- */

  PAGES.overview = function () {
    var samples = GWT.data.samples || {};
    var stages = [
      ['Site', 'site', !!store.get('site.community'), 'Project and location recorded'],
      ['Geophysics', 'ves', pageDone('ves'),
        derived.interpretations ? derived.interpretations.length + ' soundings interpreted'
          : 'No sounding loaded'],
      ['Design', 'design', pageDone('design'),
        derived.design ? C.fmtNum(derived.design.total_screen_length_m) + ' m of screen'
          : 'No design yet'],
      ['Pumping test', 'pumping', pageDone('pumping'),
        derived.analysis && derived.analysis.transmissivity_m2_per_day
          ? 'T = ' + S.sig(derived.analysis.transmissivity_m2_per_day, 3) + ' m²/day'
          : (derived.test ? 'Parsed; results pending' : 'No test loaded')],
      ['Water quality', 'quality', pageDone('quality'),
        derived.assessment
          ? (derived.assessment.health_exceedances.length
            ? derived.assessment.health_exceedances.length + ' health exceedance(s)'
            : C.VERDICT_LONG[derived.assessment.verdict_state])
          : 'No analysis loaded'],
      ['Cost', 'costing', pageDone('costing'),
        derived.estimate ? S.money(derived.estimate.total_cost_usd, 0) + ' total cost'
          : 'No estimate yet'],
    ];

    return [
      pageHead('Overview', 'The whole borehole lifecycle in one workspace: site ' +
        'the well, design it, test it, sample it, cost it and hand it over. ' +
        'Everything runs in this browser — no data is uploaded anywhere.'),

      derived.analysis || derived.assessment || derived.design
        ? card('Headline results', [
          S.statRow([
            derived.analysis && derived.analysis.transmissivity_m2_per_day
              ? S.stat('Transmissivity',
                S.sig(derived.analysis.transmissivity_m2_per_day, 3) + ' m²/day',
                'preferred method') : null,
            derived.analysis && derived.analysis.yield_recommendation.safe_yield_m3_per_h
              ? S.stat('Safe yield',
                C.yieldRangeText(derived.analysis.yield_recommendation),
                'with the stated range') : null,
            derived.design
              ? S.stat('Total depth', C.fmtNum(derived.design.total_depth_m) + ' m',
                derived.design.screens.length + ' screened section(s)') : null,
            derived.assessment && derived.assessment.wqi
              ? S.stat('Water quality index', String(derived.assessment.wqi.value),
                derived.assessment.wqi.rating) : null,
            derived.estimate
              ? S.stat('Cost per metre', S.money(derived.estimate.cost_per_meter_usd, 0),
                'total cost basis') : null,
          ].filter(Boolean)),
        ]) : null,

      card('Progress', [
        el('div.grid.grid-3', stages.map(function (stage) {
          return el('button.stat', {
            type: 'button', style: { cursor: 'pointer', textAlign: 'left' },
            onclick: function () { goto(stage[1]); },
          }, [
            el('span.stat-label', [stage[0], ' ',
              S.badge(stage[2] ? 'done' : 'to do', stage[2] ? 'ok' : null)]),
            el('span.stat-note', stage[3]),
          ]);
        })),
      ], { note: 'Click a stage to go there.' }),

      card('Start from a sample project', [
        el('p.muted', 'Each sample is a real dataset transcribed from a field ' +
          'report, and loads as the original template workbook, so it exercises ' +
          'exactly the same reader an uploaded file does.'),
        el('div.grid.grid-2', Object.keys(samples).map(function (key) {
          var sample = samples[key];
          return el('div.card', [
            el('div.card-body', [
              el('h3', sample.label),
              el('p.muted', sample.note),
              button('Load ' + sample.label.split(' - ')[0], function () {
                loadSample(key);
              }),
            ]),
          ]);
        })),
      ]),

      card('Or start from your own data', [
        el('div.grid.grid-2', [
          uploadZone('ves', 'VES field data (.xlsx)',
            'One worksheet per sounding, AB/2 · MN · apparent resistivity'),
          uploadZone('drilling', 'Drilling log (.xlsx)',
            'Depth intervals with lithology and water strikes'),
          uploadZone('pumping', 'Pumping test (.xlsx or .docx)',
            'Step or constant discharge with recovery',
            '.xlsx,.xls,.docx'),
          uploadZone('quality', 'Water quality results (.xlsx)',
            'Parameter · value · unit from the laboratory'),
        ]),
        el('p.muted', { style: { marginTop: '0.8rem' } },
          'Not sure of the layout? The Templates page has a blank workbook for ' +
          'each of these.'),
      ]),

      installCard(),

      nextStep('New to the toolkit? The guided start walks through one borehole ' +
        'from field sheet to signed report.', 'Guided start', 'guided'),
    ].filter(Boolean);
  };

  /* --- guided start --------------------------------------------------------- */

  PAGES.guided = function () {
    var steps = [
      { key: 'site', label: 'Record the site', page: 'site',
        done: !!store.get('site.community'),
        note: 'Client, community, chiefdom, district and GPS. Every report ' +
          'header and every map comes from this.' },
      { key: 'ves', label: 'Site the borehole', page: 'ves',
        done: pageDone('ves'),
        note: 'Upload the VES sheet. The app inverts each sounding, interprets ' +
          'the layers and ranks the drilling targets.' },
      { key: 'design', label: 'Design the borehole', page: 'design',
        done: pageDone('design'),
        note: 'Screens against the aquifer, casing, gravel pack and sanitary ' +
          'seal, drawn to scale.' },
      { key: 'pumping', label: 'Test the borehole', page: 'pumping',
        done: pageDone('pumping'),
        note: 'Cooper-Jacob, Theis and recovery, then a safe yield and a pump ' +
          'setting depth.' },
      { key: 'quality', label: 'Check the water', page: 'quality',
        done: pageDone('quality'),
        note: 'WHO and national limits, ionic balance, corrosivity and the ' +
          'Piper and Stiff diagrams.' },
      { key: 'costing', label: 'Cost the works', page: 'costing',
        done: pageDone('costing'),
        note: 'A bill of quantities on the RWSN model, with cost and price ' +
          'kept apart.' },
      { key: 'supervision', label: 'Supervise construction', page: 'supervision',
        done: pageDone('supervision'),
        note: 'Stage checklists and the numeric acceptance checks a supervisor ' +
          'applies on site.' },
      { key: 'handover', label: 'Hand over', page: 'handover',
        done: pageDone('handover'),
        note: 'The handover report, the data sheet and the operation and ' +
          'maintenance guidance for the community.' },
    ];
    var doneCount = steps.filter(function (s) { return s.done; }).length;

    return [
      pageHead('Guided start', 'Eight steps, in the order the work actually ' +
        'happens. Each one is a page you can also reach directly from the ' +
        'sidebar; this page just keeps the thread.'),
      card('Progress', [
        el('div.progress-track', el('div.progress-fill', {
          style: { width: (100 * doneCount / steps.length).toFixed(0) + '%' },
        })),
        el('p.muted', { style: { marginTop: '0.5rem' } },
          doneCount + ' of ' + steps.length + ' steps complete'),
      ]),
      el('div', steps.map(function (step, i) {
        return card(null, [
          el('div', { style: { display: 'flex', gap: '0.9rem', alignItems: 'flex-start' } }, [
            el('div.wizard-step' + (step.done ? '.done' : ''), [
              el('span.n', String(i + 1)),
            ]),
            el('div', { style: { flex: '1', minWidth: '0' } }, [
              el('h3', step.label),
              el('p.muted', step.note),
            ]),
            button(step.done ? 'Review' : 'Go', function () { goto(step.page); },
              { variant: step.done ? 'ghost' : undefined }),
          ]),
        ]);
      })),
    ];
  };

  /* --- site & maps ---------------------------------------------------------- */

  /* Held outside the render so the field keeps what was typed while the page
   * redraws around it. Cleared when the page is drawn fresh, so a stale
   * value cannot be converted after the input has visibly reset. */
  var latLonEntry = { text: '' };

  /* "lat, lon" as a field crew writes it.
   *
   * Every longitude in Sierra Leone is west, and a handheld GPS writes that
   * as a W rather than a minus sign. Dropping the letter and taking the
   * number at face value puts the site 26 degrees east of where it is —
   * silently, on the wrong side of the continent — so the hemisphere letter
   * is a sign, and a letter that contradicts an explicit sign is rejected
   * rather than guessed at. */
  function parseLatLon(text) {
    var raw = String(text === null || text === undefined ? '' : text).trim();
    if (!raw) return null;
    /* split on commas, semicolons and whitespace, but keep a letter attached
     * to the number it qualifies ("13.2317W" is one token) */
    var tokens = raw.replace(/[;]/g, ',').split(/[,\s]+/).filter(Boolean);
    var values = [];
    var pending = null;                 /* a leading N/S/E/W awaiting its number */
    for (var i = 0; i < tokens.length; i++) {
      var token = tokens[i];
      var bare = /^[NSEWnsew]$/.test(token);
      if (bare) {
        var letter = token.toUpperCase();
        if (values.length && values[values.length - 1].letter === null) {
          values[values.length - 1].letter = letter;   /* trailing "8.4657 N" */
        } else {
          pending = letter;                            /* leading "N 8.4657" */
        }
        continue;
      }
      var match = /^([+-]?\d*\.?\d+)\s*([NSEWnsew])?$/.exec(token);
      if (!match) return null;
      values.push({
        value: Number(match[1]),
        letter: match[2] ? match[2].toUpperCase() : pending,
      });
      pending = null;
    }
    if (values.length !== 2) return null;

    function signed(entry) {
      if (!isFinite(entry.value)) return null;
      if (!entry.letter) return entry.value;
      var negative = entry.letter === 'S' || entry.letter === 'W';
      /* "-13.2317 W" is contradictory: the sign and the letter disagree
       * about magnitude, so refuse rather than pick one */
      if (entry.value < 0 && !negative) return null;
      if (entry.value < 0 && negative) return entry.value;
      return negative ? -entry.value : entry.value;
    }

    /* the pair is normally lat then lon; an explicit E/W on the first token
     * says otherwise */
    var first = values[0], second = values[1];
    if (first.letter === 'E' || first.letter === 'W' ||
        second.letter === 'N' || second.letter === 'S') {
      var swap = first; first = second; second = swap;
    }
    var lat = signed(first), lon = signed(second);
    if (lat === null || lon === null) return null;
    if (!isFinite(lat) || !isFinite(lon)) return null;
    if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
    return { lat: lat, lon: lon };
  }

  PAGES.site = function () {
    var site = store.get('site');
    var mapRadius = store.get('site.mapRadiusKm', 40);
    /* the input below is rendered empty every time, so the buffer behind it
     * must be too — otherwise Convert acts on text the operator can no
     * longer see */
    latLonEntry.text = '';
    function bind(key) {
      return function (value) { store.set('site.' + key, value); renderChrome(); };
    }
    function bindNum(key) {
      return function (value) { store.set('site.' + key, value); render(); };
    }

    var districts = (GWT.data.districts || []).map(function (d) { return d.district; });
    var chiefdoms = (GWT.data.chiefdomDistrict || [])
      .filter(function (row) { return !site.district || row.district === site.district; })
      .map(function (row) { return row.chiefdom; });

    var latlon = siteLatLon();
    var mapNode = null;
    if (GWT.data.geo && GWT.data.geo.adminBoundaries) {
      var boundaries = GWT.data.geo.adminBoundaries.features || [];
      mapNode = charts.siteMap({
        context: boundaries,
        contextFill: function (feature) {
          var name = (feature.properties || {}).name || (feature.properties || {}).shapeName;
          return name === site.district ? '#CFE0D6' : '#EDEAE3';
        },
        points: latlon ? [{
          lon: latlon.lon, lat: latlon.lat, label: siteLabel(),
          colour: charts.palette().secondary, size: 6,
        }] : [],
        title: 'Site location',
        legendItems: latlon ? [{ label: 'Project site', colour: charts.palette().secondary }] : [],
        width: 620, height: 520,
      });
    }

    return [
      pageHead('Site & maps', 'The header block every report carries, and where ' +
        'the site sits in the country.'),

      card('Project and location', [
        el('div.grid.grid-2', [
          el('div', [
            field('Client', S.textInput(site.client, bind('client'))),
            field('Project', S.textInput(site.project, bind('project'))),
            field('Project reference', S.textInput(site.project_ref, bind('project_ref'))),
            field('Community / village', S.textInput(site.community, bind('community'))),
          ]),
          el('div', [
            field('District', S.selectInput(site.district,
              [{ value: '', label: '— select —' }].concat(districts),
              function (v) { store.set('site.district', v); render(); })),
            field('Chiefdom', S.selectInput(site.chiefdom,
              [{ value: '', label: '— select —' }].concat(chiefdoms),
              bind('chiefdom'))),
            field('Field supervisor', S.textInput(site.supervisor, bind('supervisor'))),
            field('Drilling contractor', S.textInput(site.contractor, bind('contractor'))),
          ]),
        ]),
        el('div.field-row', [
          field('GPS easting (UTM)', S.numberInput(site.easting, bindNum('easting')),
            'or a longitude in degrees'),
          field('GPS northing (UTM)', S.numberInput(site.northing, bindNum('northing')),
            'or a latitude in degrees'),
          field('UTM zone', S.selectInput(site.utm_zone || '',
            [{ value: '', label: 'infer from the easting' },
              { value: '28', label: '28N' }, { value: '29', label: '29N' }],
            function (v) { store.set('site.utm_zone', v ? Number(v) : null); render(); })),
          field('Elevation (m)', S.numberInput(site.elevation_m, bindNum('elevation_m'))),
          field('Date', S.textInput(site.date, bind('date'))),
        ]),
        /* Field crews read decimal degrees off a phone or a handheld GPS.
         * Typing them straight in removes the UTM-conversion friction and the
         * wrong-zone errors that come with it. */
        field('or paste "lat, lon" from a phone or handheld GPS',
          el('div.btn-row', [
            S.textInput('', function (value) { latLonEntry.text = value; },
              { placeholder: '8.4657, -13.2317' }),
            button('Convert to UTM', function () {
              var pair = parseLatLon(latLonEntry.text);
              if (!pair) {
                S.toast('Could not read those coordinates. Enter "lat, lon" in ' +
                  'decimal degrees — 8.4657, -13.2317 or 8.4657 N, 13.2317 W.',
                'error');
                return;
              }
              var lat = pair.lat, lon = pair.lon;
              var utm = C.geographicToUtm(lat, lon);
              store.set('site.easting', S.round(utm.easting, 1));
              store.set('site.northing', S.round(utm.northing, 1));
              store.set('site.utm_zone', utm.zone);
              S.toast('Converted to UTM zone ' + utm.zone + 'N.', 'ok');
              render();
            }, { variant: 'ghost' }),
          ])),
        latlon ? el('p.muted', 'Interpreted position: ' + latlon.lat.toFixed(5) +
          '°N, ' + latlon.lon.toFixed(5) + '°E' +
          (latlon.fromUtm ? ' (converted from UTM zone ' + latlon.zone + ')' : '') +
          (latlon.chiefdom ? ' — inside ' + latlon.chiefdom + ' chiefdom' +
            (districtOf(latlon.chiefdom) ? ', ' + districtOf(latlon.chiefdom) +
              ' district' : '') : '')) : null,
        /* the commonest copy-over error on a field sheet is a district that
         * does not contain the recorded position, so say so where it is seen */
        latlon && latlon.chiefdom && site.district &&
          districtOf(latlon.chiefdom) && districtOf(latlon.chiefdom) !== site.district
          ? el('div.callout.callout-warn', el('p',
            'The recorded district (' + site.district + ') does not contain ' +
            'these coordinates, which fall in ' + districtOf(latlon.chiefdom) +
            '. Check the sheet before the reports carry it.')) : null,
      ]),

      mapNode ? card('Where the site sits', [
        charts.figure(mapNode, 'Project location within Sierra Leone',
          { filename: 'site_location' }),
        el('p.muted', C.POPULATION_CREDIT),
      ]) : null,

      card('Geology and aquifers', [
        el('p.muted', 'Report-ready context from freely licensed datasets: ' +
          'geology from the USGS Geologic Map of Africa, and aquifer type and ' +
          'productivity from the BGS Africa Groundwater Atlas. These are the ' +
          'same layers the geophysical survey and handover reports carry.'),
        latlon ? field('Local map window (km around the site)',
          S.numberInput(mapRadius, function (value) {
            store.set('site.mapRadiusKm', S.clamp(Number(value) || 40, 5, 400));
            render();
          }, { min: 5, max: 400, step: 5 })) : el('p.muted',
          'Without site coordinates the national maps are drawn unmarked; ' +
          'enter a position above for the local window.'),
        el('div.grid.grid-2', [
          charts.figure(charts.thematicMap({
            features: (GWT.data.geo.hydrogeology || {}).features || [],
            context: (GWT.data.geo.adminBoundaries || {}).features || [],
            key: 'unit',
            window: latlon ? { lat: latlon.lat, lon: latlon.lon, radiusKm: mapRadius } : null,
            points: latlon ? [{ lon: latlon.lon, lat: latlon.lat, label: siteLabel() }] : [],
            title: latlon ? 'Aquifer productivity around the site'
              : 'Aquifer productivity, Sierra Leone',
            width: 560, height: 520,
          }), 'Aquifer type and productivity (BGS Africa Groundwater Atlas, CC BY-SA 4.0)',
          { filename: 'aquifer_map' }),
          charts.figure(charts.thematicMap({
            features: (GWT.data.geo.geology || {}).features || [],
            context: (GWT.data.geo.adminBoundaries || {}).features || [],
            key: 'unit',
            window: latlon ? { lat: latlon.lat, lon: latlon.lon, radiusKm: mapRadius } : null,
            points: latlon ? [{ lon: latlon.lon, lat: latlon.lat, label: siteLabel() }] : [],
            title: latlon ? 'Geology around the site' : 'Geology, Sierra Leone',
            width: 560, height: 520,
          }), 'Geology (USGS Geologic Map of Africa)', { filename: 'geology_map' }),
        ]),
      ]),

      nextStep('With the site recorded, upload the geophysical survey to choose ' +
        'the drilling point.', 'Geophysics', 'ves'),
    ];
  };

  /* Sierra Leone lies in UTM zones 28N and 29N; the easting alone identifies
   * the zone, so it is inferred rather than guessed. A pair of small numbers is
   * read as degrees instead. */
  function siteLatLon() {
    var site = store.get('site');
    var e = site.easting, n = site.northing;
    if (e === null || n === null || e === undefined || n === undefined) return null;
    if (Math.abs(e) <= 180 && Math.abs(n) <= 90) {
      return { lon: e, lat: n, fromUtm: false, chiefdom: chiefdomAt(n, e) };
    }
    var zone = site.utm_zone || C.inferZoneForSierraLeone(e);
    var ll = utmToLatLon(e, n, zone);
    if (!ll) return null;
    ll.fromUtm = true; ll.zone = zone;
    ll.chiefdom = chiefdomAt(ll.lat, ll.lon);
    return ll;
  }

  function districtOf(chiefdom) {
    if (!chiefdom) return '';
    return (C.loadChiefdomDistrict() || {})[chiefdom] || '';
  }

  function chiefdomAt(lat, lon) {
    try {
      return C.chiefdomOfPoint(lat, lon, polygons());
    } catch (e) { return ''; }
  }

  var _polys = null;
  function polygons() {
    if (!_polys) _polys = C.loadPolygons();
    return _polys;
  }

  /* WGS84 inverse transverse Mercator, northern hemisphere. */
  /* One implementation of the projection, in the engine, so the map, the
   * report and the coverage join can never place the same borehole in two
   * places. */
  function utmToLatLon(easting, northing, zone) {
    return C.utmToGeographic(easting, northing, zone);
  }

  /* --- geophysics ----------------------------------------------------------- */

  PAGES.ves = function () {
    var nodes = [
      pageHead('Geophysics (VES)', 'Vertical electrical soundings inverted to ' +
        'layered earth models, interpreted for the crystalline basement, and ' +
        'ranked into a drilling preference table.'),
      card('Sounding data', [
        uploadZone('ves', 'VES field data (.xlsx)',
          'One worksheet per sounding: AB/2, MN and apparent resistivity'),
        derived.soundings ? el('p.muted', derived.soundings.length + ' ' +
          S.plural(derived.soundings.length, 'sounding') + ' read: ' +
          derived.soundings.map(function (s) { return s.sounding_id; }).join(', ')) : null,
      ], {
        actions: derived.soundings ? [
          button('Re-run inversion', function () {
            runInversions({ quiet: false }).then(render);
          }, { variant: 'ghost' }),
        ] : null,
      }),
    ];

    if (!derived.soundings || !derived.soundings.length) {
      nodes.push(S.empty('No sounding loaded yet. Upload a VES workbook, or ' +
        'load the Rokel sample from the Overview page.',
        button('Overview', function () { goto('overview'); }, { variant: 'ghost' })));
      return nodes;
    }

    var allFlags = [];
    derived.soundings.forEach(function (s) {
      (s.flags || []).forEach(function (f) {
        allFlags.push({ level: f.level, message: f.message, detail: f.context });
      });
    });
    if (allFlags.length) nodes.push(card('Data checks', [S.checkList(allFlags)]));

    if (!derived.inversions || !derived.inversions.length) {
      nodes.push(S.empty('The soundings are loaded but not yet inverted.',
        button('Invert now', function () { runInversions({ quiet: false }).then(render); })));
      return nodes;
    }

    var cfg = config();
    derived.inversions.forEach(function (result, i) {
      var interp = derived.interpretations[i];
      var sounding = derived.soundings[i];
      var curve = charts.vesCurve(result);
      var model = charts.layeredModel(result.model, {
        maxDepth: Math.max(interp.investigation_depth_m, 20),
      });
      nodes.push(card(sounding.sounding_id + ' — ' +
        C.describeCurveType(interp.curve_type).split(';')[0], [
        S.statRow([
          S.stat('Fit error', result.fit_error_percent.toFixed(1) + '%',
            result.model.n_layers + ' layers, ' + result.n_iterations + ' iterations'),
          S.stat('Depth to bedrock', interp.depth_to_basement_m !== null
            ? C.fmtNum(interp.depth_to_basement_m) + ' m' : 'not resolved'),
          S.stat('Aquifer thickness', C.fmtNum(interp.aquifer_thickness_m) + ' m',
            interp.water_zones.length + ' zone(s)'),
          S.stat('Max drilling depth',
            interp.max_drilling_depth_m.toFixed(0) + ' m',
            'capped at the investigated depth'),
          S.stat('Protective capacity', interp.protective_capacity,
            'S = ' + C.fmtNum(interp.protective_conductance_s, 3) + ' S'),
        ]),
        el('div.split.split-figure', [
          charts.figure(curve, 'Sounding curve for ' + sounding.sounding_id, {
            filename: 'ves_' + S.slug(sounding.sounding_id),
            table: function () {
              return S.table([
                { key: 'ab2', label: 'AB/2 (m)', align: 'right' },
                { key: 'obs', label: 'Measured (Ω·m)', align: 'right' },
                { key: 'calc', label: 'Model (Ω·m)', align: 'right' },
              ], result.ab2.map(function (v, k) {
                return {
                  ab2: S.sig(v, 4), obs: S.sig(result.rho_obs[k], 4),
                  calc: S.sig(result.rho_calc[k], 4),
                };
              }));
            },
          }),
          charts.figure(model, 'Layered model for ' + sounding.sounding_id,
            { filename: 'model_' + S.slug(sounding.sounding_id) }),
        ]),
        S.table([
          { key: 'number', label: 'Layer' },
          { key: 'rho', label: 'Resistivity (Ω·m)', align: 'right',
            format: function (v, row) {
              return C.fmtNum(row.rho, 4) +
                (row.factor ? '  ×/÷ ' + row.factor.toFixed(1) : '');
            } },
          { key: 'thickness_m', label: 'Thickness (m)', align: 'right',
            format: function (v) { return v === null ? '—' : C.fmtNum(v); } },
          { key: 'top_m', label: 'Top (m)', align: 'right',
            format: function (v) { return C.fmtNum(v); } },
          { key: 'bottom_m', label: 'Bottom (m)', align: 'right',
            format: function (v) { return isFinite(v) ? C.fmtNum(v) : '—'; } },
          { key: 'unit', label: 'Interpretation' },
        ], interp.layers.map(function (layer, k) {
          return Object.assign({}, layer, {
            factor: result.rho_uncertainty_factor ? result.rho_uncertainty_factor[k] : null,
          });
        }), {
          rowClass: function (row) { return row.water_bearing ? 'row-ok' : ''; },
        }),
        el('p', interp.narrative),
        result.rho_uncertainty_factor ? el('p.muted',
          'The ×/÷ figures are the one-sigma multiplicative uncertainty on each ' +
          'resistivity: a factor near 1 is well resolved, a large one marks the ' +
          'equivalence that makes resistivity models non-unique.') : null,
      ]));
    });

    var preferenceRows = C.drillingPreferenceTable(derived.interpretations,
      store.get('ves.preferredOrder'));
    nodes.push(card('Drilling preference', [
      S.table([
        { key: 'No.', label: 'No.' },
        { key: 'VES Point', label: 'VES point' },
        { key: 'Possible Water Zones (m)', label: 'Possible water zones (m)' },
        { key: 'Max Drilling Depth (m)', label: 'Max depth' },
        { key: 'Ranking', label: 'Ranking' },
      ], preferenceRows, {
        rowClass: function (row) { return row.Ranking === '1st' ? 'row-ok' : ''; },
      }),
      el('p.muted', 'Ranking follows the suitability score: thickness of the ' +
        'interpreted water bearing zones, weighted towards resistivities in the ' +
        'productive window. Where sites score close together the choice is a ' +
        'professional judgment call — set the order explicitly below.'),
      field('Preferred order (most preferred first, comma separated)',
        S.textInput((store.get('ves.preferredOrder') || []).join(', '),
          function (value) {
            store.set('ves.preferredOrder', value.split(',')
              .map(function (s) { return s.trim(); }).filter(Boolean));
            C.rankInterpretations(derived.interpretations, store.get('ves.preferredOrder'));
            render();
          })),
    ]));

    var suitability = C.assessSiting(derived.interpretations, config().ves);
    var best = suitability[0];
    var located = suitability.filter(function (s) {
      return s.easting && s.northing;
    });
    if (best) nodes.push(card('Drill-target suitability', [
      el('p.muted', 'A transparent 0-100 score per point, combining the ' +
        'interpreted aquifer thickness, how central the water-zone resistivity ' +
        'sits in the productive window, the weathered profile and any fracture ' +
        'at the basement contact. The weights are a defensible default, not a ' +
        'calibrated model: as real drilling outcomes accumulate they can be ' +
        'replaced by a fitted one.'),
      el('div.callout.callout-ok', [
        el('p', el('strong', 'Recommended drill target: ' + best.sounding_id +
          ' (' + best.suitability.toFixed(0) + '/100, ' + best.grade + ')')),
        el('p', best.rationale),
      ]),
      S.table([
        { key: 'rank', label: 'Rank', align: 'right' },
        { key: 'sounding_id', label: 'Point' },
        { key: 'suitability', label: 'Suitability', align: 'right',
          format: function (v) { return v.toFixed(0) + '/100'; } },
        { key: 'grade', label: 'Grade' },
        { key: 'rationale', label: 'Why' },
      ], suitability, {
        rowClass: function (row) { return row.rank === 1 ? 'row-ok' : ''; },
      }),
      located.length ? charts.figure(charts.siteMap({
        context: (GWT.data.geo.chiefdomBoundaries || {}).features || [],
        points: located.map(function (s) {
          var ll = utmToLatLon(s.easting, s.northing,
            store.get('site.utm_zone') || C.inferZoneForSierraLeone(s.easting));
          if (!ll) return null;
          return {
            lon: ll.lon, lat: ll.lat, label: s.sounding_id,
            size: 4 + s.suitability / 25,
            colour: s.suitability >= 75 ? charts.palette().good
              : (s.suitability >= 55 ? charts.palette().cat[2]
                : (s.suitability >= 35 ? charts.palette().warning
                  : charts.palette().critical)),
          };
        }).filter(Boolean),
        title: 'Drill-target suitability',
        legendItems: [
          { label: 'Very good', colour: charts.palette().good },
          { label: 'Good', colour: charts.palette().cat[2] },
          { label: 'Moderate', colour: charts.palette().warning },
          { label: 'Poor', colour: charts.palette().critical },
        ],
        width: 640, height: 520,
      }), 'Candidate points scored for drilling', { filename: 'suitability_map' })
        : el('p.muted', 'Add GPS coordinates to the VES points to draw the ' +
          'drill-target map.'),
    ]));

    nodes.push(reportCard('Geophysical survey report', 'geophysical',
      'Introduction, geology, field work, per-sounding interpretation, the ranked ' +
      'preference table, conclusions and the limitations of the method.'));

    nodes.push(nextStep('With a target chosen, set out the borehole construction.',
      'Borehole design', 'design'));
    return nodes;
  };

  /* --- borehole design ------------------------------------------------------ */

  PAGES.design = function () {
    var custom = store.get('design');
    var interp = bestInterpretation();
    var cfg = config();
    var nodes = [
      pageHead('Borehole design', 'Screens against the aquifer and below the ' +
        'static level, plain casing, a sump, gravel pack, backfill and a cement ' +
        'sanitary seal — assembled by the rules in Settings and drawn to scale.'),
    ];

    var suggestedDepth = (derived.log && derived.log.total_depth_m) ||
      (interp && interp.max_drilling_depth_m) || null;

    nodes.push(card('Design inputs', [
      el('div.field-row', [
        field('Total depth (m)', S.numberInput(
          custom.totalDepth !== null && custom.totalDepth !== undefined
            ? custom.totalDepth : suggestedDepth,
          function (v) { store.set('design.totalDepth', v); rebuildDesign(); rebuildCosting(); render(); }),
          derived.log && derived.log.total_depth_m
            ? 'from the drilling log'
            : (interp ? 'from the VES recommendation' : 'enter the drilled depth')),
        field('Static water level (m)', S.numberInput(
          derived.test ? derived.test.static_water_level_m : null,
          function () {}, { disabled: true }),
          'from the pumping test sheet'),
        field('Pump intake (m)', S.numberInput(
          custom.pumpIntake !== null && custom.pumpIntake !== undefined
            ? custom.pumpIntake
            : (derived.analysis && derived.analysis.yield_recommendation
              ? derived.analysis.yield_recommendation.pump_installation_depth_m : null),
          function (v) { store.set('design.pumpIntake', v); rebuildDesign(); render(); }),
          'from the yield recommendation unless overridden'),
      ]),
      uploadZone('drilling', 'Drilling log (.xlsx)',
        'Optional — screens follow the logged water strikes when present'),
    ]));

    if (!derived.design) {
      nodes.push(S.empty('A total depth is needed before a design can be ' +
        'assembled — from a drilling log, a VES interpretation, or typed above.'));
      return nodes;
    }

    var design = derived.design;
    nodes.push(card('Construction', [
      S.statRow([
        S.stat('Total depth', C.fmtNum(design.total_depth_m) + ' m'),
        S.stat('Screen', C.fmtNum(design.total_screen_length_m) + ' m',
          design.screens.length + ' section(s), slot ' +
          C.fmtNum(design.screen_slot_mm) + ' mm'),
        S.stat('Casing', design.casing_diameter_in + '" ' + design.casing_material,
          'in a ' + design.borehole_diameter_in + '" hole'),
        S.stat('Gravel pack', design.gravel_pack[0].toFixed(0) + '–' +
          design.gravel_pack[1].toFixed(0) + ' m'),
      ]),
      design.flags.length ? S.checkList(design.flags.map(function (f) {
        return { level: f.level, message: f.message };
      })) : null,
      el('div.split', [
        charts.figure(charts.boreholeDesign(design, derived.log),
          'Borehole construction design', { filename: 'borehole_design' }),
        el('div', [
          S.table([
            { key: '0', label: 'Item' }, { key: '1', label: 'Detail' },
          ], C.designSummaryRows(design).map(function (row) {
            return { 0: row[0], 1: row[1] };
          })),
          el('h4', 'Design basis'),
          el('ul', design.design_basis.map(function (b) { return el('li', b); })),
        ]),
      ]),
    ]));

    nodes.push(card('Screen placement', [
      el('p.muted', 'Screens are placed automatically against the water strikes ' +
        'in the drilling log, the aquifer intervals in the lithology, or the ' +
        'low resistivity zones of the VES interpretation. Override them here ' +
        'when the driller\'s judgement on site differs; an analyst-placed ' +
        'screen is validated by exactly the same checks.'),
      S.editableTable([
        { key: 'top', label: 'Top (m)', type: 'number' },
        { key: 'bottom', label: 'Bottom (m)', type: 'number' },
      ], (custom.screens || design.screens.map(function (s) {
        return { top: s.top_m, bottom: s.bottom_m };
      })), function (rows) {
        var screens = rows.filter(function (r) {
          return S.isNum(r.top) && S.isNum(r.bottom) && r.bottom > r.top;
        }).map(function (r) { return [r.top, r.bottom]; });
        store.set('design.screens', screens.length ? screens : null);
        rebuildDesign(); rebuildCosting();
      }, { addLabel: '+ Add screen interval' }),
      button('Reset to automatic placement', function () {
        store.set('design.screens', null); rebuildDesign(); rebuildCosting(); render();
      }, { variant: 'ghost' }),
    ]));

    nodes.push(reportCard('Borehole completion report', 'completion',
      'Introduction, methodology, drilling record, the borehole log table and ' +
      'the as-built construction.'));
    nodes.push(nextStep('Next, analyse the pumping test to get a yield.',
      'Pumping test', 'pumping'));
    return nodes;
  };

  /* --- depth spine ---------------------------------------------------------- */

  /* The sign-off layer, as a layer rather than a second application.
   *
   * Every stage produces one professional opinion. The toolkit recommends it,
   * a named person accepts or overrides it, and an override carries a reason
   * that travels into the report. The ledger lives in the project state, so it
   * is saved with the project and survives a refresh - a signature that
   * evaporated on reload would be worth nothing. */
  var SPINE_STAGES = [
    ['design', 'Design'], ['quality', 'Water quality'], ['costing', 'Costing & BoQ'],
  ];

  function spineLedger() { return store.get('spine.ledger') || {}; }

  function spineSignatory() {
    return store.get('spine.signatory') ||
      store.get('site.supervisor') || 'unsigned';
  }

  function spineDecide(stage, record) {
    var ledger = Object.assign({}, spineLedger());
    if (record) ledger[stage] = record; else delete ledger[stage];
    store.set('spine.ledger', ledger);
    render();
  }

  function spineStamp() {
    return new Date().toISOString().slice(0, 16).replace('T', ' ');
  }

  /* Accepting is one press. Overriding costs a value and a reason, because the
   * override is the thing that ends up in front of the client with a name on
   * it. */
  function signOffCard(spec) {
    var record = spineLedger()[spec.stage] || null;
    if (record) {
      return card('Signed off', [
        el('div.callout' + (record.status === 'accepted' ? '.callout-ok' : '.callout-warn'), [
          el('p', el('strong',
            (record.status === 'accepted' ? 'Accepted' : 'Overridden') +
            ' — ' + record.value)),
          el('p.muted', record.signatory + ' · ' + record.at +
            (record.clean ? '' : ' · signed over an open flag')),
          record.status === 'overridden' ? el('p', [
            el('span.muted', 'The toolkit recommended ' + record.recommended + '. '),
            record.reason,
          ]) : null,
        ]),
        button('Reopen decision', function () { spineDecide(spec.stage, null); },
          { variant: 'ghost' }),
      ]);
    }
    var overrideValue = { value: spec.overrideStart, reason: '' };
    var open = store.get('spine.overriding') === spec.stage;
    return card('Sign off', [
      el('p.muted', spec.writesTo +
        (spec.clean ? '.' : ' · one check is still flagged.')),
      field('Signatory', S.textInput(spineSignatory(), function (value) {
        store.set('spine.signatory', value);
      }), 'Named on the decision, and in the report.'),
      open ? el('div.section', [
        spec.overrideChoices
          ? field(spec.overrideLabel, S.selectInput(spec.overrideStart,
            spec.overrideChoices, function (value) { overrideValue.value = value; }))
          : field(spec.overrideLabel + ' (' + spec.overrideUnit + ')',
            S.numberInput(spec.overrideStart, function (value) {
              overrideValue.value = value;
            }, { step: spec.overrideStep || 0.01 })),
        field('Reason — required, and it goes in the report',
          S.textInput('', function (value) { overrideValue.reason = value; })),
        el('div.btn-row', [
          button('Record override', function () {
            if (!String(overrideValue.reason).trim()) {
              S.toast('An override needs a reason.', 'warn');
              return;
            }
            store.set('spine.overriding', null);
            spineDecide(spec.stage, {
              stage: spec.stage, status: 'overridden',
              value: spec.formatOverride
                ? spec.formatOverride(overrideValue.value) : String(overrideValue.value),
              recommended: spec.recommended,
              reason: String(overrideValue.reason).trim(),
              signatory: spineSignatory(), at: spineStamp(), clean: spec.clean,
            });
          }),
          button('Cancel', function () {
            store.set('spine.overriding', null); render();
          }, { variant: 'ghost' }),
        ]),
      ]) : null,
      el('div.btn-row', [
        button('Accept ' + (spec.acceptLabel || spec.recommended), function () {
          spineDecide(spec.stage, {
            stage: spec.stage, status: 'accepted', value: spec.recommended,
            recommended: spec.recommended, signatory: spineSignatory(),
            at: spineStamp(), clean: spec.clean,
          });
        }),
        open ? null : button('Override…', function () {
          store.set('spine.overriding', spec.stage); render();
        }, { variant: 'ghost' }),
      ]),
    ]);
  }

  function flagList(flags, empty) {
    if (!flags || !flags.length) {
      return el('div.callout.callout-ok', el('p', empty));
    }
    return S.checkList(flags.map(function (f) {
      return {
        level: f.level, message: f.message,
        detail: f.code + (f.context ? ' · ' + f.context : ''),
      };
    }));
  }

  /* Moving a screen re-runs the design and everything downstream of it, and
   * invalidates the design and costing signatures: a signature has to belong
   * to the numbers that were in front of the person at the time. */
  function commitSpineScreens(screens) {
    store.set('design.screens', screens && screens.length
      ? screens.map(function (s) { return [s.top, s.base]; }) : null);
    var ledger = Object.assign({}, spineLedger());
    delete ledger.design; delete ledger.costing;
    store.set('spine.ledger', ledger);
    rebuildDesign(); rebuildCosting();
    render();
  }

  /* Direct manipulation of the screened intervals. Dragging moves the drawing
   * locally, because a pointer has to feel attached to what it is dragging;
   * releasing hands the intervals back to the engine, which re-runs
   * designBorehole and everything downstream. No hydrogeological rule is
   * applied here - the clamping is only enough to keep the drawing sane while
   * the pointer is down; the real validation is the designer's. */
  function attachScreenDrag(svg, view, redraw) {
    var limits = view.section.screenLimits;
    var base = (view.design.screens || []).map(function (s) {
      return { top: s.top, base: s.base };
    });

    function round(n) { return Math.round(n * 10) / 10; }
    function clamp(list) {
      return list.map(function (s) {
        var top = Math.max(limits.top, Math.min(s.top, limits.base - limits.minLength));
        var bottom = Math.max(top + limits.minLength, Math.min(s.base, limits.base));
        return { top: round(top), base: round(bottom) };
      });
    }
    function moved(origin, index, edge, dm) {
      return clamp(origin.map(function (s, i) {
        if (i !== index) return { top: s.top, base: s.base };
        if (edge === 'top') return { top: round(s.top + dm), base: s.base };
        if (edge === 'base') return { top: s.top, base: round(s.base + dm) };
        return { top: round(s.top + dm), base: round(s.base + dm) };
      }));
    }

    svg.addEventListener('pointerdown', function (event) {
      var target = event.target;
      var index = target.getAttribute && target.getAttribute('data-screen');
      if (index === null || index === undefined) return;
      event.preventDefault();
      var edge = target.getAttribute('data-edge');
      var startY = event.clientY;
      var origin = base.map(function (s) { return { top: s.top, base: s.base }; });
      var latest = origin;
      var scale = svg.spineScale;
      /* the SVG is scaled to its box, so client pixels become user units
       * through the rendered height before they become metres. A zero-height
       * box (hidden tab, mid-layout) would make that ratio infinite and send
       * the screen to the bottom of the hole on the first move. */
      var rendered = svg.getBoundingClientRect().height;
      if (!(rendered > 0)) return;
      var factor = svg.viewBox.baseVal.height / rendered;

      function move(e) {
        var dm = round(scale.depthAt((e.clientY - startY) * factor));
        latest = moved(origin, Number(index), edge, dm);
        redraw(latest);
      }
      function end() {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', end);
        window.removeEventListener('pointercancel', end);
        commitSpineScreens(latest);
      }
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', end);
      window.addEventListener('pointercancel', end);
    });

    svg.addEventListener('keydown', function (event) {
      var target = event.target;
      var index = target.getAttribute && target.getAttribute('data-screen');
      if (index === null || index === undefined) return;
      var edge = target.getAttribute('data-edge');
      if (edge === 'body') return;
      var step = event.shiftKey ? 1 : 0.1;
      var dm = event.key === 'ArrowUp' ? -step : (event.key === 'ArrowDown' ? step : 0);
      if (!dm) return;
      event.preventDefault();
      commitSpineScreens(moved(base, Number(index), edge, dm));
    });
  }

  PAGES.spine = function () {
    var head = pageHead('Depth Spine', 'The whole borehole on one depth axis: ' +
      'the cuttings log, the casing string and the water levels registered ' +
      'against the same ruler, with the screened intervals editable. ' +
      'Everything shown is computed here, by the same functions that write ' +
      'the reports.');

    if (!derived.log) {
      return [head, S.empty('Load a drilling log first — the spine is drawn ' +
        'from the logged hole.',
      el('div.btn-row', [
        button('Borehole design', function () { goto('design'); }),
        button('Overview', function () { goto('overview'); }, { variant: 'ghost' }),
      ]))];
    }

    var view;
    try {
      view = C.buildSpineView({
        name: store.get('site.community') || 'Borehole',
        log: derived.log, analysis: derived.analysis,
        assessment: derived.assessment, config: config(),
        mobilisationDistanceKm: store.get('costing.mobilisation_km') || 0,
      }, store.get('design.screens'));
    } catch (e) {
      return [head, el('div.callout.callout-bad', [
        el('p', el('strong', 'The spine could not be built.')),
        el('p', e.message),
      ])];
    }

    var stage = store.get('spine.stage', 'design');
    var stages = SPINE_STAGES.filter(function (s) {
      return s[0] !== 'quality' || view.quality;
    });
    if (!stages.some(function (s) { return s[0] === stage; })) stage = 'design';
    var ledger = spineLedger();
    var signed = stages.filter(function (s) { return ledger[s[0]]; }).length;

    var nodes = [head, card('Stage', [
      el('div.chips', stages.map(function (s) {
        var record = ledger[s[0]];
        return el('button.chip' + (stage === s[0] ? '.active' : ''), {
          type: 'button',
          onclick: function () { store.set('spine.stage', s[0]); render(); },
        }, [s[1], record ? ' ' : null,
          record ? S.badge(record.status === 'accepted' ? '✓' : '↺',
            record.status === 'accepted' ? 'ok' : 'warn') : null]);
      })),
      el('p.muted', signed + ' of ' + stages.length + ' stages signed. ' +
        (view.edited ? 'The design on this section is the analyst\'s, not the ' +
          'automatic placement.' : 'Screens are the automatic placement.')),
    ])];

    if (stage === 'design') nodes = nodes.concat(spineDesignStage(view));
    else if (stage === 'quality') nodes = nodes.concat(spineQualityStage(view));
    else nodes = nodes.concat(spineCostingStage(view));

    nodes.push(nextStep('Price the design on the section.', 'Costing & BoQ', 'costing'));
    return nodes;
  };

  function spineDesignStage(view) {
    var section = view.section, design = view.design, y = design.yield;
    var errors = design.flags.filter(function (f) { return f.level === 'error'; });
    var clean = !errors.length &&
      design.flags.every(function (f) { return f.level === 'info'; });

    /* one holder redrawn in place, so a drag does not re-render the page */
    var holder = el('div');
    function draw(screens) {
      S.clear(holder);
      var svg = charts.depthSpine(view, { screens: screens, width: 720, height: 640 });
      attachScreenDrag(svg, view, draw);
      holder.appendChild(svg);
    }
    draw(null);

    return [
      card('The hole', [
        S.statRow([
          S.stat('Drilled', section.totalDepth.toFixed(1) + ' m'),
          S.stat('Water strikes', section.waterStrikes.length
            ? section.waterStrikes.map(function (s) { return s.toFixed(0); }).join(', ') + ' m'
            : 'none'),
          S.stat('Screened', design.totalScreenM + ' m',
            design.screenShare + '% of the hole'),
          S.stat('Casing', section.casingDiameterIn + '″ ' + section.casingMaterial,
            'slot ' + section.slotMm + ' mm'),
        ]),
        holder,
        el('p.muted', 'Drag a screen or one of its handles, or focus a handle ' +
          'and use the arrow keys — 0.1 m a press, 1 m with Shift. On release ' +
          'the toolkit re-runs the design: the casing string, the annulus, the ' +
          'checks and the bill of quantities all come back from the engine, so ' +
          'nothing here is a second opinion. The Borehole design page and the ' +
          'completion report follow the same screens.'),
        view.edited ? button('Back to the generated design', function () {
          commitSpineScreens(null);
        }, { variant: 'ghost' }) : null,
      ]),

      card('Recommended safe yield', y.pending ? [
        el('div.callout.callout-warn', [
          el('p', el('strong', 'Pending')),
          el('p', y.pending),
        ]),
      ] : [
        S.statRow([
          S.stat('Safe yield', y.rangeText || (y.safeYieldM3PerH + ' m³/h'),
            'projected to ' + y.designPeriodDays + ' days, safety factor ' +
            y.safetyFactor),
          S.stat('Transmissivity', y.transmissivity + ' m²/day', 'preferred method'),
          S.stat('Pump setting', y.pumpDepthM + ' m', 'below ground level'),
          S.stat('Specific capacity', y.specificCapacity + ' m³/h per m'),
        ]),
        y.methods && y.methods.length ? S.table([
          { key: 'label', label: 'Method' },
          { key: 'transmissivity', label: 'T (m²/day)', align: 'right' },
        ], y.methods.concat([
          { label: 'Preferred', transmissivity: y.transmissivity },
        ])) : null,
        el('p.muted', y.basis + (y.envelopeBasis ? ' ' + y.envelopeBasis : '')),
      ]),

      card('Design basis', [
        design.basis.length
          ? el('ul', design.basis.map(function (b) { return el('li', b); }))
          : el('p.muted', 'No basis recorded.'),
      ]),

      card('Flags on this design', [
        flagList(design.flags, 'No flags raised on the design or the test.'),
      ]),

      signOffCard({
        stage: 'design', clean: clean,
        recommended: y.pending ? 'a pending yield' : (y.rangeText || 'the design'),
        acceptLabel: 'the design',
        writesTo: 'Accepting writes to the completion and pumping-test reports',
        overrideLabel: 'Certified safe yield', overrideUnit: 'm³/h',
        overrideStart: y.safeYieldM3PerH || 0, overrideStep: 0.01,
        formatOverride: function (n) { return n + ' m³/h'; },
      }),
    ];
  }

  function spineQualityStage(view) {
    var q = view.quality;
    var judged = q.rows.filter(function (r) { return r.status !== 'no_guideline'; });
    /* Only rows the toolkit actually graded and found compliant. Counting
     * every non-"exceeds" status as within limits put the unevaluable and
     * the unmeasured in the compliant column. */
    var within = judged.filter(function (r) {
      return r.status === 'within_limits' || r.status === 'below_detection';
    });
    var ungraded = judged.filter(function (r) {
      return r.status === 'indeterminate' || r.status === 'not_measured';
    });
    /* Driven by the verdict state, so an unevaluable panel can never be
     * signed off as "Complies". */
    var headline = {
      health_fail: 'Not suitable for drinking',
      national_fail: 'Fails the national standard',
      indeterminate: 'Not proven safe — results incomplete',
      aesthetic: 'Potable — acceptability exceeded',
      pass: 'Complies',
    }[q.verdictState] || 'Not proven safe — results incomplete';
    var clean = q.verdictState === 'pass';
    var cor = q.corrosivity;
    var spine = charts.guidelineSpine(q.rows);

    return [
      card('The sample', [
        S.statRow([
          S.stat('Sampled', q.sampleDate || '—', q.laboratory || ''),
          S.stat('Within limits', within.length + ' / ' + judged.length,
            ungraded.length ? ungraded.length + ' could not be graded' : ''),
          S.stat('Health exceedances',
            q.healthExceedances.length ? String(q.healthExceedances.length) : 'none'),
          q.ionic ? S.stat('Ionic balance', q.ionic.errorPercent + ' %',
            'against a ±5 % acceptance limit') : null,
          cor ? S.stat('Corrosivity', cor.classification) : null,
        ].filter(Boolean)),
        spine ? charts.figure(spine,
          'Every determinand as a multiple of its own binding limit',
          { filename: 'guideline_spine' }) : null,
        el('p.muted', 'Limits come from the toolkit\'s standards table — the ' +
          'WHO health-based guideline value, the WHO acceptability value and ' +
          'the national standard, whichever binds.'),
      ]),

      q.ionic ? card('Ionic balance', [
        S.statRow([
          S.stat('Σ cations', q.ionic.cationsMeq + ' meq/L'),
          S.stat('Σ anions', q.ionic.anionsMeq + ' meq/L'),
          S.stat('Error', (q.ionic.errorPercent > 0 ? '+' : '') +
            q.ionic.errorPercent + ' %'),
        ]),
        el('p.muted', Math.abs(q.ionic.errorPercent) <= 5
          ? 'The analysis is internally consistent, so the rest of this page ' +
            'can be relied on.'
          : 'The analysis does not balance; treat every figure here with caution.'),
        q.ionic.usedAlkalinity
          ? el('p.muted', 'Bicarbonate was inferred from alkalinity.') : null,
      ]) : null,

      cor ? card('Corrosivity indices', [
        S.table([
          { key: '0', label: 'Index' }, { key: '1', label: 'Value' },
        ], [
          ['Langelier (LSI)', cor.lsi], ['Ryznar (RSI)', cor.rsi],
          ['Aggressive index', cor.aggressiveIndex],
          ['Larson-Skold', cor.larsonSkold],
          ['Classification', cor.classification],
        ]),
        el('div.callout' + (cor.isAggressive ? '.callout-warn' : '.callout-ok'), [
          el('p', el('strong', 'Handpump materials')),
          el('p', cor.materialsNote || cor.verdict),
        ]),
        cor.assumptions.length
          ? el('p.muted', cor.assumptions.join(' ')) : null,
      ]) : null,

      q.piper ? card('Hydrochemical facies', [
        el('div.grid.grid-2', [
          charts.figure(charts.piper([derived.sample]), 'Piper diagram',
            { filename: 'piper' }),
          charts.figure(charts.stiff(derived.sample), 'Stiff diagram',
            { filename: 'stiff' }),
        ]),
      ]) : null,

      card('Exceedances', [
        S.table([
          { key: '0', label: 'Against' },
          { key: '1', label: 'Parameters' },
        ], [
          ['Health-based', q.healthExceedances.join(', ') || 'none'],
          ['National standard', q.nationalExceedances.join(', ') || 'none'],
          ['Acceptability', q.aestheticExceedances.join(', ') || 'none'],
        ]),
        el('p', q.verdict),
        q.wqi ? el('p.muted', 'Water quality index ' + q.wqi.value +
          ' — ' + q.wqi.rating + '.') : null,
        q.nationalExceedances.length ? provisionalStandardsNote() : null,
      ].filter(Boolean)),

      card('Flags on this analysis', [
        flagList(q.flags, 'No flags raised on the sample.'),
      ]),

      signOffCard({
        stage: 'quality', clean: clean, recommended: headline,
        acceptLabel: 'the verdict',
        writesTo: 'Accepting writes to the water-quality and handover reports',
        overrideLabel: 'Certified verdict', overrideUnit: '',
        overrideStart: headline,
        overrideChoices: ['Complies', 'Potable — acceptability exceeded',
          'Potable after treatment', 'Not proven safe — results incomplete',
          'Fails the national standard', 'Not suitable for drinking'],
      }),
    ].filter(Boolean);
  }

  function spineCostingStage(view) {
    var c = view.costing;
    var stages = [];
    c.items.forEach(function (i) {
      if (stages.indexOf(i.stage) < 0) stages.push(i.stage);
    });

    /* the lines the design drives, so the analyst can see what moved with it */
    var designDriven = /casing|screen|gravel|grout|seal|drill/i;
    var boqRows = [];
    stages.forEach(function (stageName) {
      var lines = c.items.filter(function (i) { return i.stage === stageName; });
      var subtotal = lines.reduce(function (a, l) { return a + l.amount; }, 0);
      boqRows.push({ item: stageName, subtotal: true, amount: subtotal });
      lines.forEach(function (line) {
        boqRows.push({
          item: line.item, unit: line.unit, quantity: line.quantity,
          unitCost: line.unitCost, amount: line.amount,
          derived: designDriven.test(line.item), note: line.note,
        });
      });
    });

    return [
      card('What it costs', [
        S.statRow([
          S.stat('Direct cost', S.money(c.directCost, 0)),
          S.stat('Cost to build', S.money(c.totalCost, 0),
            'direct + ' + c.overheadsPercent + '% overheads'),
          S.stat('Price to client', S.money(c.price, 0),
            'cost + ' + c.marginPercent + '% margin'),
          S.stat('Per metre', S.money(c.costPerMetre, 0), 'cost basis'),
        ]),
        el('p.muted', 'RWSN Cost-Effective Boreholes: quantities come from the ' +
          'design on the section, and the contractor\'s cost is kept apart ' +
          'from the client\'s price.' +
          (c.contingencyPercent > 0 ? ' A ' + c.contingencyPercent +
            '% client-side contingency is shown separately on the Costing ' +
            'page, so the contract price stays honest.' : '')),
      ]),

      card('Bill of quantities', [
        S.table([
          { key: 'item', label: 'Item' },
          { key: 'unit', label: 'Unit' },
          { key: 'quantity', label: 'Quantity', align: 'right' },
          { key: 'unitCost', label: 'Unit cost (US$)', align: 'right',
            format: function (v) { return v === undefined ? '' : S.money(v, 2); } },
          { key: 'amount', label: 'Amount (US$)', align: 'right',
            format: function (v) { return S.money(v, 0); } },
        ], boqRows, {
          rowClass: function (row) { return row.subtotal ? 'row-warn' : ''; },
        }),
        el('p.muted', 'Quantities on the casing, screen, gravel pack, grout and ' +
          'drilling lines move with the screens on the section: both come from ' +
          'the same design object.'),
        c.assumptions.length ? el('div.section', [
          el('h4.section-title', 'Assumptions filled in where the design is silent'),
          el('ul', c.assumptions.map(function (a) { return el('li', a); })),
        ]) : null,
      ]),

      card('Where the money goes', [
        el('div.grid.grid-2', [
          S.section('By stage', S.table([
            { key: 'label', label: 'Stage' },
            { key: 'amount', label: 'US$', align: 'right',
              format: function (v) { return S.money(v, 0); } },
            { key: 'share', label: 'Share', align: 'right',
              format: function (v) { return v + '%'; } },
          ], c.byStage)),
          S.section('By resource category', S.table([
            { key: 'label', label: 'Category' },
            { key: 'amount', label: 'US$', align: 'right',
              format: function (v) { return S.money(v, 0); } },
            { key: 'share', label: 'Share', align: 'right',
              format: function (v) { return v + '%'; } },
          ], c.byCategory)),
        ]),
        S.section('Quantities from the design', S.table([
          { key: '0', label: 'Quantity' }, { key: '1', label: 'Value' },
        ], [
          ['Total depth', c.quantityBasis.totalDepthM + ' m'],
          ['Plain casing', c.quantityBasis.casingM + ' m'],
          ['Screen', c.quantityBasis.screenM + ' m'],
          ['Gravel pack interval', c.quantityBasis.gravelIntervalM + ' m'],
          ['Overburden', (c.quantityBasis.overburdenM === null
            ? '—' : c.quantityBasis.overburdenM + ' m')],
        ])),
      ]),

      card('Flags on this estimate', [
        flagList(c.flags, 'No flags raised on the estimate.'),
      ]),

      signOffCard({
        stage: 'costing',
        clean: c.flags.every(function (f) { return f.level === 'info'; }),
        recommended: S.money(c.price, 0),
        acceptLabel: 'the price',
        writesTo: 'Accepting writes to the cost estimate and the bill of quantities',
        overrideLabel: 'Price to client', overrideUnit: 'US$',
        overrideStart: Math.round(c.price), overrideStep: 50,
        formatOverride: function (n) { return S.money(n, 0); },
      }),
    ];
  }

  /* --- pumping test --------------------------------------------------------- */

  PAGES.pumping = function () {
    var nodes = [
      pageHead('Pumping test', 'Cooper-Jacob, Theis and recovery on the same ' +
        'readings, a step drawdown analysis where the test has steps, and a safe ' +
        'yield reported as a range over the assumptions it rests on.'),
      card('Test data', [
        uploadZone('pumping', 'Pumping test sheet (.xlsx or .docx)',
          'The standard workbook, or a Word field sheet: step or constant ' +
          'discharge, with the recovery block',
          '.xlsx,.xls,.docx'),
      ]),
    ];

    if (!derived.test) {
      nodes.push(S.empty('No pumping test loaded. Upload a sheet, or load the ' +
        'Dr Timbo or Kuntoloh sample from the Overview page.',
        button('Overview', function () { goto('overview'); }, { variant: 'ghost' })));
      return nodes;
    }

    var test = derived.test, analysis = derived.analysis;

    nodes.push(card('Discharge per step', [
      el('p.muted', 'Discharge is often left off the field sheet. Enter the ' +
        'bucket-and-stopwatch figures here and every pending result is computed ' +
        'immediately — the value belongs to the project, not to the file, so it ' +
        'survives a re-upload.'),
      S.table([
        { key: 'label', label: 'Step' },
        { key: 'n', label: 'Readings', align: 'right' },
        { key: 'tmax', label: 'Duration (min)', align: 'right' },
        { key: 'q', label: 'Discharge (m³/h)', align: 'right' },
      ], test.steps.map(function (step) {
        return {
          label: step.label, n: step.time_min.length,
          tmax: C.fmtNum(Math.max.apply(null, step.time_min)),
          q: S.numberInput(step.discharge_m3_per_h, function (value) {
            store.set('pumping.manualDischarges.' + step.step_number, value);
            recompute().then(render);
          }, { step: 'any', class: 'input cell', style: { maxWidth: '9rem' } }),
        };
      })),
    ]));

    if (analysis.flags.length) {
      nodes.push(card('Data checks', [S.checkList(analysis.flags.map(function (f) {
        return { level: f.level, message: f.message, detail: f.context };
      }))]));
    }

    nodes.push(card('Field data', [
      charts.figure(charts.testOverview(test, analysis),
        'Water level through the pumping and recovery phases',
        { filename: 'test_overview' }),
    ]));

    var methodFigures = [];
    var cj = charts.cooperJacob(analysis);
    if (cj) methodFigures.push(charts.figure(cj, 'Cooper-Jacob straight line fit',
      { filename: 'cooper_jacob' }));
    var rec = charts.recovery(analysis);
    if (rec) methodFigures.push(charts.figure(rec, 'Theis recovery analysis',
      { filename: 'recovery' }));
    var stepFig = charts.stepTest(analysis);
    if (stepFig) methodFigures.push(charts.figure(stepFig,
      'Step drawdown analysis', { filename: 'step_test' }));

    if (methodFigures.length) {
      nodes.push(card('Analysis', [
        el('div.split', methodFigures),
        S.table([
          { key: 'method', label: 'Method' },
          { key: 'T', label: 'Transmissivity (m²/day)', align: 'right' },
          { key: 'note', label: 'Note' },
        ], [
          analysis.recovery ? {
            method: 'Theis recovery',
            T: S.sig(analysis.recovery.transmissivity_m2_per_day, 4),
            note: 'r² = ' + analysis.recovery.r_squared.toFixed(3) +
              ' — least affected by well losses, so preferred',
          } : null,
          analysis.cooper_jacob ? {
            method: 'Cooper-Jacob',
            T: S.sig(analysis.cooper_jacob.transmissivity_m2_per_day, 4),
            note: analysis.cooper_jacob.u_check,
          } : null,
          analysis.theis ? {
            method: 'Theis type curve',
            T: S.sig(analysis.theis.transmissivity_m2_per_day, 4),
            note: 'S = ' + S.sig(analysis.theis.storativity, 2) +
              (analysis.theis.storativity_reliable ? ''
                : ' — not resolvable from a single pumped well'),
          } : null,
        ].filter(Boolean)),
      ]));
    }

    var rec2 = analysis.yield_recommendation;
    nodes.push(card('Yield recommendation', [
      rec2.safe_yield_m3_per_h ? S.statRow([
        S.stat('Safe yield', C.yieldRangeText(rec2),
          'range over the assumptions it rests on'),
        S.stat('Long term yield',
          rec2.long_term_yield_m3_per_h.toFixed(2) + ' m³/h',
          'before the ' + rec2.safety_factor + '× safety factor'),
        S.stat('Specific capacity', rec2.specific_capacity_m3hr_per_m
          ? rec2.specific_capacity_m3hr_per_m.toFixed(2) + ' m³/h per m' : '—'),
        S.stat('Pump setting', rec2.pump_installation_depth_m !== null
          ? rec2.pump_installation_depth_m.toFixed(0) + ' m' : '—'),
      ]) : el('div.callout.callout-warn', el('p',
        'Yield recommendation pending: ' + rec2.pending_reason + '.')),
      el('p', rec2.basis),
      rec2.envelope_basis ? el('div.callout', el('p', rec2.envelope_basis)) : null,
      rec2.safe_yield_m3_per_h ? el('p.muted',
        'At 20 litres per person per day over an eight hour pumping day, the ' +
        'safe yield serves about ' +
        S.thousands(Math.round(rec2.safe_yield_m3_per_h * 1000 * 8 / 20)) +
        ' people — use the lower end of the range where the supply must not ' +
        'fail in a dry year.') : null,
    ]));

    nodes.push(seasonalCard(derived.analysis));
    nodes.push(reportCard('Pumping test report', 'pumping',
      'Test details, the full field data tables, each analysis method with its ' +
      'figure, the results summary and the yield recommendation.'));
    nodes.push(nextStep('Next, assess the water quality.', 'Water quality', 'quality'));
    return nodes;
  };

  /* The month the test was run and the size of the annual swing, and what
   * the yield becomes at the end of the dry season and in a drought year. A
   * test measures one day; the borehole has to supply the village on the
   * worst one, and those are months apart. */
  function seasonalSettings() {
    var stored = store.get('seasonal') || {};
    return {
      month: stored.month === undefined ? null : stored.month,
      rangeM: stored.rangeM === undefined ? null : stored.rangeM,
      touched: !!stored.touched,
    };
  }

  function currentSeasonal(analysis) {
    var chosen = seasonalSettings();
    var cfg = config();
    return C.seasonalYield(analysis, cfg.pumping, {
      month: chosen.touched ? chosen.month : undefined,
      annualRangeM: chosen.rangeM,
    });
  }

  function seasonalCard(analysis) {
    if (!analysis) return null;
    var chosen = seasonalSettings();
    var cfg = config();
    var read = C.monthOf(analysis.test && analysis.test.site
      ? analysis.test.site.date : '');
    var result = currentSeasonal(analysis);
    var months = [{ value: '0', label: 'not known' }].concat(
      C.MONTH_NAMES.map(function (name, i) {
        return { value: String(i + 1), label: name };
      }));
    var nodes = [
      el('p.muted', 'A pumping test measures one day. The borehole has to ' +
        'supply the village on the worst day, and those are months apart: the ' +
        'water table is highest at the end of the rains and lowest in April ' +
        'or May, so when the test was run changes what it proves.'),
      el('div.field-row', [
        field('Month the test was run',
          S.selectInput(String((chosen.touched ? chosen.month : read.month) || 0),
            months, function (v) {
              store.set('seasonal', Object.assign({}, store.get('seasonal') || {},
                { month: Number(v) || null, touched: true }));
              render();
            }), 'Read from the field sheet where it can be'),
        field('Annual water-table swing (m)',
          S.numberInput(chosen.rangeM === null
            ? cfg.pumping.seasonal_allowance_m : chosen.rangeM,
          function (v) {
            store.set('seasonal', Object.assign({}, store.get('seasonal') || {},
              { rangeM: (v === null || v === undefined) ? null : Number(v) }));
            render();
          }, { min: 0, max: 30, step: 0.5 }),
        'Wet-season high to dry-season low. A single test cannot measure it'),
      ]),
    ];
    if (result.month_note) {
      nodes.push(el('div.callout.callout-warn', el('p', result.month_note)));
    }
    if (!result.is_established) {
      nodes.push(el('p.muted', result.pending_reason ||
        'The seasonal projection is not available for this test.'));
      return card('Through the year', nodes);
    }

    nodes.push(el('p', result.summary));
    nodes.push(S.table(
      ['Scenario', 'Further decline (m)', 'Static level (m)',
        'Available drawdown (m)', 'Safe yield (m3/h)', 'Pump intake (m)'],
      result.scenarios.map(function (sc) {
        return [sc.title, C.pyFixed(sc.decline_m, 1),
          C.fmtNum(sc.static_water_level_m), C.fmtNum(sc.available_drawdown_m),
          C.fmtNum(sc.safe_yield_m3_per_h),
          C.fmtNum(sc.pump_installation_depth_m)];
      })));
    if (result.dry_season_loss_percent > 1) {
      nodes.push(el('div.callout.callout-warn', el('p',
        'By the end of the dry season this borehole yields about ' +
        C.pyFixed(result.dry_season_loss_percent, 0) + '% less than it did on ' +
        'the day of the test. Size the supply on the dry-season figure.')));
    }
    if (result.pump_installation_depth_m !== null) {
      nodes.push(el('div.callout', el('p', 'Set the pump intake at ' +
        C.fmtNum(result.pump_installation_depth_m) + ' m — deep enough for ' +
        'the drought case. The pump is fitted once, and one that draws air in ' +
        'a bad year loses the village its borehole in the year it is needed ' +
        'most.')));
    }
    nodes.push(S.checkList(result.scenarios.map(function (sc) {
      return { level: 'info', message: sc.title + ' — ' + sc.note };
    })));
    nodes.push(el('p.muted', 'The annual range used is ' +
      C.pyFixed(result.annual_range_m, 1) + ' m — ' + result.range_source +
      '. It is the one number here a single test cannot measure, and every ' +
      'figure in the table moves with it.'));
    return card('Through the year', nodes);
  }

  /* --- water quality -------------------------------------------------------- */

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
        el('div.split', [
          piperNode ? charts.figure(piperNode, 'Piper trilinear diagram',
            { filename: 'piper' }) : null,
          stiffNode ? charts.figure(stiffNode, 'Stiff diagram',
            { filename: 'stiff' }) : null,
        ]),
      ]));
    }

    nodes.push(photoCard('quality', 'Sampling photographs'));
    nodes.push(reportCard('Water quality report', 'quality',
      'Sample details, the full comparison table, the ionic balance, corrosivity ' +
      'and materials, the facies diagrams and the recommendations.'));
    nodes.push(nextStep('Next, cost the works.', 'Costing & BoQ', 'costing'));
    return nodes;
  };

  /* --- costing -------------------------------------------------------------- */

  PAGES.costing = function () {
    var costing = store.get('costing');
    function bindCost(key, rebuild) {
      return function (value) {
        store.set('costing.' + key, value);
        rebuildCosting();
        render();
      };
    }
    var nodes = [
      pageHead('Costing & bill of quantities', 'The RWSN Borehole Costing Model: ' +
        'every line carries a construction stage and a resource category, and the ' +
        "contractor's cost is kept distinct from the client's price."),
      card('Inputs', [
        el('div.field-row', [
          field('Total depth (m)', S.numberInput(
            derived.design ? derived.design.total_depth_m : costing.total_depth_m,
            bindCost('total_depth_m')),
            derived.design ? 'from the borehole design' : 'no design yet'),
          field('Mobilisation, one way (km)',
            S.numberInput(costing.mobilisation_km, bindCost('mobilisation_km'))),
          field('Water quality samples',
            S.numberInput(costing.wq_samples, bindCost('wq_samples'))),
          field('Handpumps', S.numberInput(costing.handpumps, bindCost('handpumps')),
            'set 0 when the pump is a separate contract'),
        ]),
        el('div.field-row', [
          field('Overheads (%)', S.numberInput(costing.overheads, bindCost('overheads'))),
          field('Margin (%)', S.numberInput(costing.margin, bindCost('margin'))),
          field('Contingency (%)', S.numberInput(costing.contingency, bindCost('contingency'))),
          field('VAT / GST (%)', S.numberInput(costing.vat, bindCost('vat'))),
          field('Exchange rate (SLE per US$)',
            S.numberInput(costing.exchange, bindCost('exchange'))),
        ]),
      ]),
    ];

    if (!derived.estimate) {
      nodes.push(S.empty('Enter a total depth (or produce a borehole design) to ' +
        'build the bill of quantities.'));
      return nodes;
    }

    var estimate = derived.estimate;
    nodes.push(card('Cost summary', [
      S.statRow([
        S.stat('Direct works', S.money(estimate.direct_cost_usd, 0)),
        S.stat('Total cost', S.money(estimate.total_cost_usd, 0),
          'including ' + estimate.overheads_percent + '% overheads'),
        S.stat('Cost per metre', S.money(estimate.cost_per_meter_usd, 0)),
        S.stat('Contract price', S.money(estimate.price_usd, 0),
          'with ' + estimate.margin_percent + '% margin'),
        S.stat('Planning budget', S.money(estimate.budget_usd, 0),
          'with ' + estimate.contingency_percent + '% contingency'),
      ]),
      el('div.split', [
        charts.figure(charts.costBreakdown(estimate, { mode: 'stage' }),
          'Direct cost by construction stage', { filename: 'cost_by_stage' }),
        charts.figure(charts.costBreakdown(estimate, { mode: 'category' }),
          'Direct cost by resource category', { filename: 'cost_by_category' }),
      ]),
      estimate.assumptions.length ? el('div', [
        el('h4', 'Assumptions where a figure was not supplied'),
        el('ul', estimate.assumptions.map(function (t) { return el('li.muted', t); })),
      ]) : null,
      estimate.flags.length ? S.checkList(estimate.flags.map(function (f) {
        return { level: f.level, message: f.message };
      })) : null,
    ]));

    nodes.push(card('Bill of quantities', [
      S.table([
        { key: 'Code', label: 'Code' }, { key: 'Stage', label: 'Stage' },
        { key: 'Item', label: 'Item' }, { key: 'Unit', label: 'Unit' },
        { key: 'Quantity', label: 'Qty', align: 'right',
          format: function (v) { return S.thousands(v, 2); } },
        { key: 'Rate (USD)', label: 'Rate (US$)', align: 'right',
          format: function (v) { return S.thousands(v, 2); } },
        { key: 'Amount (USD)', label: 'Amount (US$)', align: 'right',
          format: function (v) { return S.thousands(v, 2); } },
      ], estimate.boq_rows()),
      el('div.btn-row', [
        button('Download BoQ (.xlsx)', async function () {
          var rows = estimate.boq_rows();
          var header = Object.keys(rows[0]);
          var sheets = [
            { name: 'BoQ', rows: [header].concat(rows.map(function (r) {
              return header.map(function (h) { return r[h]; });
            })) },
            { name: 'Summary', rows: [['Item', 'US$', 'SLE']].concat([
              ['Direct works cost', estimate.direct_cost_usd, estimate.in_local(estimate.direct_cost_usd)],
              ['Overheads', estimate.overheads_usd, estimate.in_local(estimate.overheads_usd)],
              ['Total cost', estimate.total_cost_usd, estimate.in_local(estimate.total_cost_usd)],
              ['Margin', estimate.margin_usd, estimate.in_local(estimate.margin_usd)],
              ['Contract price', estimate.price_usd, estimate.in_local(estimate.price_usd)],
              ['Contingency', estimate.contingency_usd, estimate.in_local(estimate.contingency_usd)],
              ['Planning budget', estimate.budget_usd, estimate.in_local(estimate.budget_usd)],
            ]) },
          ];
          var bytes = await S.writeXlsx(sheets);
          S.download(S.slug(siteLabel()) + '_boq.xlsx', new Blob([bytes]));
        }, { variant: 'ghost' }),
      ]),
    ]));

    nodes.push(card('Unit rates', [
      el('p.muted', 'The bundled rates are indicative and must be confirmed ' +
        'against current local prices before the estimate is used in a tender. ' +
        'Edit any rate here; blank restores the catalogue value.'),
      S.table([
        { key: 'code', label: 'Code' }, { key: 'stage', label: 'Stage' },
        { key: 'item', label: 'Item' }, { key: 'unit', label: 'Unit' },
        { key: 'rate', label: 'Rate (US$)', align: 'right' },
      ], C.loadRates().map(function (rate) {
        return {
          code: rate.code, stage: rate.stage, item: rate.item, unit: rate.unit,
          rate: S.numberInput(
            (costing.rateOverrides || {})[rate.code] !== undefined
              ? costing.rateOverrides[rate.code] : rate.unit_cost_usd,
            function (value) {
              store.set('costing.rateOverrides.' + rate.code, value);
              rebuildCosting(); render();
            }, { step: 'any', class: 'input cell', style: { maxWidth: '7rem' } }),
        };
      })),
    ]));

    nodes.push(card('Programme of works', [
      el('div.field-row', [
        field('Successful boreholes required',
          S.numberInput(costing.programme_n, bindCost('programme_n'))),
        field('Siting success rate (%)',
          S.numberInput(costing.success_rate, bindCost('success_rate')),
          'the rest are budgeted as dry attempts'),
        field('Average move between sites (km)',
          S.numberInput(costing.inter_site_km, bindCost('inter_site_km'))),
      ]),
      derived.programme ? el('div', [
        S.statRow([
          S.stat('Attempts planned', String(derived.programme.n_attempted),
            'for ' + derived.programme.n_successful + ' successful boreholes'),
          S.stat('Programme cost', S.money(derived.programme.total_cost_usd, 0)),
          S.stat('Price per borehole',
            S.money(derived.programme.price_per_successful_well_usd, 0),
            'carrying the expected dry attempts'),
          S.stat('Planning budget', S.money(derived.programme.budget_usd, 0)),
        ]),
        charts.figure(charts.programmeGantt(derived.programme),
          'Indicative programme of works', { filename: 'programme' }),
        el('ul', derived.programme.assumptions.map(function (t) {
          return el('li.muted', t);
        })),
      ]) : el('p.muted', 'Set more than one borehole to see the package estimate.'),
    ]));

    nodes.push(reportCard('Cost estimate report', 'costing',
      'Method, the basis of the estimate, the full bill of quantities, the cost ' +
      'and price summary and the exclusions.'));
    nodes.push(nextStep('Next, the supervision checklists.', 'Supervision', 'supervision'));
    return nodes;
  };

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
          return {
            section: item.section, text: item.text, critical: item.critical,
            answer: S.selectInput(response.status || 'pending',
              [{ value: 'pending', label: '—' }, { value: 'yes', label: 'Yes' },
               { value: 'no', label: 'No' }, { value: 'na', label: 'N/A' }],
              function (value) {
                store.set('supervision.responses.' + item.item_id,
                  { item_id: item.item_id, status: value, remark: response.remark || '' });
                render();
              }, { class: 'input cell', style: { maxWidth: '6rem' } }),
            remark: S.textInput(response.remark || '', function (value) {
              store.set('supervision.responses.' + item.item_id,
                { item_id: item.item_id, status: response.status || 'pending', remark: value });
            }, { class: 'input cell' }),
          };
        }), {
          rowClass: function (row) {
            var r = responses[stageItems[0] ? '' : ''] || {};
            return '';
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

    nodes.push(photoCard('supervision', 'Supervision photographs'));
    nodes.push(reportCard('Supervision record', 'supervision',
      'The summary, the full checklist record stage by stage, the field ' +
      'acceptance checks and the sign-off block.', { fieldChecks: fieldChecks }));
    nodes.push(nextStep('Finally, hand the borehole over.', 'Handover', 'handover'));
    return nodes;
  };

  /* --- handover ------------------------------------------------------------- */

  PAGES.handover = function () {
    var handover = store.get('handover');
    var nodes = [
      pageHead('Handover', 'The document the community and the district water ' +
        'office keep: what was built, what it yields, whether the water is safe ' +
        'and how to look after it.'),
      card('Handover details', [
        el('div.field-row', [
          field('Handover date', S.textInput(handover.date, function (v) {
            store.set('handover.date', v);
          })),
        ]),
        el('h4', 'Water and sanitation committee'),
        S.editableTable([
          { key: 'name', label: 'Name' },
          { key: 'role', label: 'Role' },
          { key: 'contact', label: 'Contact' },
        ], handover.committee || [], function (rows) {
          store.set('handover.committee', rows);
        }, { addLabel: '+ Add member' }),
      ]),
    ];

    var ready = [
      ['Borehole design', !!derived.design, 'design'],
      ['Pumping test', !!derived.analysis, 'pumping'],
      ['Water quality', !!derived.assessment, 'quality'],
    ];
    nodes.push(card('What the handover report will carry', [
      S.table([
        { key: 'item', label: 'Input' },
        { key: 'state', label: 'State',
          format: function (v) { return S.badge(v ? 'ready' : 'missing', v ? 'ok' : 'warn'); } },
        { key: 'action', label: '' },
      ], ready.map(function (r) {
        return {
          item: r[0], state: r[1],
          action: r[1] ? '' : button('Go', function () { goto(r[2]); }, { variant: 'ghost' }),
        };
      })),
      el('p.muted', 'A missing input does not block the report; the section ' +
        'simply says what still has to be done.'),
    ]));

    nodes.push(photoCard('handover', 'Handover photographs'));
    nodes.push(photoCard('completion', 'Construction photographs'));
    nodes.push(reportCard('Project handover report', 'handover',
      'Project summary, works completed, the borehole data sheet, water quality, ' +
      'operation and maintenance guidance, the committee and the signature block.'));
    return nodes;
  };

  /* --- templates ------------------------------------------------------------ */

  var TEMPLATE_SPECS = {
    ves: {
      label: 'VES field data', file: 'ves_template.xlsx',
      sheets: function () {
        return [{ name: 'VES 1', rows: [
          ['SCHLUMBERGER ARRAY VES FIELD DATA'],
          ['Client', '', 'Community', ''],
          ['Project', '', 'Sounding Number', 'VES 1'],
          ['District', '', 'Chiefdom', ''],
          ['GPS Coordinate East', '', 'GPS Coordinate North', ''],
          ['Elevation', '', 'Date', ''],
          ['Field Supervisor', '', 'Instrument', ''],
          [],
          ['No.', 'AB/2 (m)', 'MN (m)', 'Apparent Resistivity (ohm-m)'],
          [1, 1.5, 0.5, ''], [2, 2, 0.5, ''], [3, 3, 0.5, ''], [4, 4, 0.5, ''],
          [5, 6, 0.5, ''], [6, 8, 0.5, ''], [7, 10, 0.5, ''], [8, 15, 0.5, ''],
          [9, 15, 5, ''], [10, 20, 5, ''], [11, 25, 5, ''], [12, 30, 5, ''],
          [13, 40, 5, ''], [14, 50, 5, ''], [15, 60, 5, ''], [16, 80, 5, ''],
          [17, 100, 5, ''],
        ] }];
      },
      note: 'One worksheet per sounding. Repeat an AB/2 with the new MN at a ' +
        'segment change — both readings are kept.',
    },
    drilling: {
      label: 'Drilling log', file: 'drilling_log_template.xlsx',
      sheets: function () {
        return [{ name: 'Drilling Log', rows: [
          ['BOREHOLE DRILLING LOG'],
          ['Community', '', 'Client', ''],
          ['Contractor', '', 'Borehole Ref. No.', ''],
          ['District', '', 'Chiefdom', ''],
          ['Drilling Method', '', 'Drill Rig', ''],
          ['Start Date', '', 'Completion Date', ''],
          ['Total Depth', '', 'BH Status', ''],
          ['Grouting Depth', '', '', ''],
          [],
          ['Depth Interval (m)', 'From', 'To', 'Penetration rate (m/min)',
            'Sample description / lithology', 'Bit diameter (in)', 'Water strike (m)'],
          ['0-3', '', '', '', '', '', ''],
          ['3-6', '', '', '', '', '', ''],
          ['6-9', '', '', '', '', '', ''],
        ] }];
      },
      note: 'Format the depth column as Text before typing "5-10", or Excel ' +
        'converts it to a date and the row is skipped.',
    },
    pumping: {
      label: 'Pumping test', file: 'pumping_test_template.xlsx',
      sheets: function () {
        var rows = [
          ['PUMPING TEST FIELD SHEET (STEP / CONSTANT DISCHARGE)'],
          ['Community', '', '', 'Date', '', '', 'GPS Coordinate East', ''],
          ['Client', '', '', 'Length of each step (min)', '', '', 'GPS Coordinate North', ''],
          ['Borehole Ref. No.', '', '', 'Test Type', 'step', '', 'Depth of Borehole', ''],
          ['Static Water Level', '', '', 'Pump Setting', '', '', 'Test conducted by', ''],
          ['Step 1 Q (m3/h)', '', 'Step 2 Q (m3/h)', '', 'Step 3 Q (m3/h)', '',
            'Step 4 Q (m3/h)', ''],
          [],
          ['Time (min)', 'Water Level (m)', 'Drawdown (m)',
            'Time (min)', 'Water Level (m)', 'Drawdown (m)',
            'Time (min)', 'Water Level (m)', 'Recovery (m)'],
        ];
        [1, 2, 3, 4, 5, 6, 8, 10, 15, 20, 25, 30, 40, 50, 60].forEach(function (t) {
          rows.push([t, '', '', t, '', '', t, '', '']);
        });
        return [{ name: 'Pumping Test', rows: rows }];
      },
      note: 'The Drawdown and Recovery columns are the increment between ' +
        'readings; the toolkit never uses them — true drawdown is recomputed ' +
        'from water level minus static level.',
    },
    quality: {
      label: 'Water quality results', file: 'water_quality_template.xlsx',
      sheets: function () {
        var params = [
          ['pH', 'pH units'], ['Temperature', 'deg C'],
          ['Electrical conductivity', 'uS/cm'], ['TDS', 'mg/L'],
          ['Turbidity', 'NTU'], ['Total hardness', 'mg/L'], ['Alkalinity', 'mg/L'],
          ['Calcium', 'mg/L'], ['Magnesium', 'mg/L'], ['Sodium', 'mg/L'],
          ['Potassium', 'mg/L'], ['Chloride', 'mg/L'], ['Sulfate', 'mg/L'],
          ['Bicarbonate', 'mg/L'], ['Nitrate', 'mg/L'], ['Nitrite', 'mg/L'],
          ['Ammonia', 'mg/L'], ['Iron', 'mg/L'], ['Manganese', 'mg/L'],
          ['Fluoride', 'mg/L'], ['Arsenic', 'mg/L'], ['Lead', 'mg/L'],
          ['E. coli', 'CFU/100mL'], ['Total coliforms', 'CFU/100mL'],
        ];
        return [{ name: 'Water Quality', rows: [
          ['WATER QUALITY LABORATORY RESULTS'],
          ['Community', '', 'Client', ''],
          ['Sample ID', '', 'Borehole Ref. No.', ''],
          ['Sample Date', '', 'Laboratory', ''],
          [],
          ['Parameter', 'Value', 'Unit', 'Detection limit', 'Method'],
        ].concat(params.map(function (p) { return [p[0], '', p[1], '', '']; })) }];
      },
      note: 'Write "<0.01" for a below-detection result; the value is then ' +
        'treated as unknown rather than as a concentration equal to the limit.',
    },
  };

  PAGES.templates = function () {
    return [
      pageHead('Templates', 'Blank workbooks in exactly the layout the readers ' +
        'expect. Fill one in the field, upload it, and every analysis follows.'),
      el('div.grid.grid-2', Object.keys(TEMPLATE_SPECS).map(function (key) {
        var spec = TEMPLATE_SPECS[key];
        return card(spec.label, [
          el('p.muted', spec.note),
          button('Download ' + spec.file, async function () {
            var bytes = await S.writeXlsx(spec.sheets());
            S.download(spec.file, new Blob([bytes]));
          }),
        ]);
      })),
      card('All four at once', [
        button('Download every template', async function () {
          for (var key in TEMPLATE_SPECS) {
            if (!Object.prototype.hasOwnProperty.call(TEMPLATE_SPECS, key)) continue;
            var spec = TEMPLATE_SPECS[key];
            var bytes = await S.writeXlsx(spec.sheets());
            S.download(spec.file, new Blob([bytes]));
            await new Promise(function (r) { setTimeout(r, 250); });
          }
        }),
      ]),
    ];
  };

  /* --- scanned sheets ------------------------------------------------------- */

  var SCAN_MIME = {
    pdf: 'application/pdf', png: 'image/png', jpg: 'image/jpeg',
    jpeg: 'image/jpeg', webp: 'image/webp', gif: 'image/gif',
  };

  async function buildReviewWorkbook(document) {
    var bytes = await S.writeXlsx(C.reviewWorkbookSheets(document));
    var stem = String(document.source).replace(/\.[^.]+$/, '') || 'scan';
    S.download(stem + '_review.xlsx', new Blob([bytes]));
  }

  async function buildFilledVesTemplate(document) {
    var blank = TEMPLATE_SPECS.ves.sheets()[0];
    var rows = C.fillVesTemplateSheets(document, blank.rows);
    var bytes = await S.writeXlsx([{ name: 'VES 1', rows: rows }]);
    var stem = String(document.source).replace(/\.[^.]+$/, '') || 'scan';
    S.download(stem + '_ves_template.xlsx', new Blob([bytes]));
  }

  PAGES.extract = function () {
    var doc = derived.extraction;
    var apiKey = getApiKey();
    var nodes = [
      pageHead('Scanned sheets', 'A sheet that arrived as a PDF or a photograph, ' +
        'turned into the same records an uploaded template produces. A PDF with ' +
        'a text layer is read here in the page; a photograph has no text to ' +
        'read and goes to Claude. Uncertain values are highlighted in the ' +
        'review workbook, never silently accepted.'),
      card('Read a sheet', [
        el('p.muted', 'PDF, PNG, JPEG or WebP. Nothing is uploaded for the ' +
          'text-layer path — the whole PDF reader runs in this page.'),
        el('div.btn-row', [
          button('Read a text PDF', async function (event) {
            var file = await S.pickFile('.pdf,application/pdf');
            if (!file) return;
            var host = event.target.closest('.card');
            try {
              await S.withBusy(host, 'Reading the PDF…', async function () {
                var bytes = new Uint8Array(await S.readFile(file, 'arrayBuffer'));
                derived.extraction = await C.extractPdfText(bytes, file.name);
              });
              S.toast('Read a ' + derived.extraction.document_kind + ' sheet.', 'ok');
            } catch (e) {
              S.toast(e.message, 'error');
            }
            render();
          }),
          button('AI assisted extraction', async function (event) {
            if (!apiKey) {
              S.toast('Set an Anthropic API key on the Settings page first.', 'warn');
              goto('settings');
              return;
            }
            var file = await S.pickFile('.pdf,.png,.jpg,.jpeg,.webp');
            if (!file) return;
            var host = event.target.closest('.card');
            try {
              await S.withBusy(host, 'Transcribing the sheet with Claude…',
                async function () {
                  var bytes = new Uint8Array(await S.readFile(file, 'arrayBuffer'));
                  var extension = (file.name.split('.').pop() || '').toLowerCase();
                  derived.extraction = await C.extractWithClaude({
                    apiKey: apiKey,
                    model: store.get('extraction.model') || undefined,
                    base64: S.bytesToBase64(bytes),
                    mediaType: file.type || SCAN_MIME[extension] || 'application/pdf',
                    source: file.name,
                  });
                });
              S.toast('Transcribed a ' + derived.extraction.document_kind + ' sheet.', 'ok');
            } catch (e) {
              S.toast(e.message, 'error');
            }
            render();
          }, { variant: 'ghost' }),
          doc ? button('Clear', function () {
            derived.extraction = null; render();
          }, { variant: 'ghost' }) : null,
        ]),
        !apiKey ? el('p.muted', 'The AI path needs an Anthropic API key, set on ' +
          'the Settings page. It is the only feature here that sends anything ' +
          'anywhere, and it sends the sheet to Anthropic.') : null,
      ]),
    ];

    if (!doc) {
      nodes.push(S.empty('Nothing read yet. A field sheet printed from the ' +
        'templates carries a text layer and reads straight through; a photo of ' +
        'a handwritten sheet needs the AI path.'));
      return nodes;
    }

    var items = C.reviewItems(doc);
    nodes.push(card('What was read', [
      S.statRow([
        S.stat('Sheet type', doc.document_kind.replace(/_/g, ' ')),
        S.stat('Header fields', String(doc.header.length)),
        S.stat('Tables', String(doc.tables.length)),
        S.stat('To review', String(items.length),
          items.length ? 'checked by hand before use' : 'nothing flagged'),
      ]),
      el('p.muted', doc.notes + ' Extractor: ' + doc.extractor + '.'),
      el('div.btn-row', [
        button('Download review workbook (.xlsx)', function () {
          buildReviewWorkbook(doc);
        }),
        doc.document_kind === 'ves' && doc.tables.length
          ? button('Download filled VES template (.xlsx)', function () {
            try {
              buildFilledVesTemplate(doc);
            } catch (e) { S.toast(e.message, 'error'); }
          }, { variant: 'ghost' }) : null,
      ]),
    ]));

    if (doc.header.length) {
      nodes.push(card('Header fields', [
        S.table([
          { key: 'name', label: 'Field' },
          { key: 'value', label: 'Value' },
          { key: 'confidence', label: 'Confidence', align: 'right',
            format: function (v) { return v.toFixed(2); } },
        ], doc.header, {
          rowClass: function (row) { return row.needs_review ? 'row-warn' : ''; },
        }),
      ]));
    }

    doc.tables.forEach(function (table, index) {
      nodes.push(card(table.title, [
        S.table(table.columns.map(function (column, i) {
          return { key: String(i), label: column || ('Column ' + (i + 1)) };
        }), table.rows, {
          rowClass: function (row, i) {
            return C.confidenceForRow(table, i) < C.REVIEW_THRESHOLD ? 'row-warn' : '';
          },
        }),
        el('p.muted', table.rows.length + ' ' + S.plural(table.rows.length, 'row') +
          ' read from table ' + (index + 1) + '.'),
      ]));
    });

    nodes.push(card('Needs a human', [
      items.length
        ? el('ul', items.map(function (item) { return el('li', item); }))
        : el('div.callout.callout-ok', el('p',
          'Nothing flagged: every value was read with high confidence. Spot ' +
          'check it anyway before it becomes a report.')),
      el('p.muted', 'Correct the flagged values in the review workbook, then ' +
        'upload the corrected sheet on the page that needs it. Extraction ' +
        'never writes into the project on its own.'),
    ]));
    nodes.push(nextStep('Blank templates for the field team are on the ' +
      'Templates page.', 'Templates', 'templates'));
    return nodes;
  };

  /* --- water points --------------------------------------------------------- */

  /* The lookup is the only thing in the application that leaves the machine,
   * so it is always a button the operator presses, never something the page
   * does on its own. Failure is expected in the field and is not an error
   * state: the CSV path below does the whole job offline.
   *
   * ``spec.clip`` decides what the returned inventory means. A site lookup
   * clips to the circle the operator asked for, so the functionality totals
   * describe that radius and nothing else. The national pull does not: its
   * bounding box deliberately overhangs into Guinea and Liberia, and the
   * chiefdom join — not a distance — is what discards the fringe. */
  async function lookUpWaterPoints(node, spec) {
    try {
      await S.withBusy(node.closest('.card') || $('#page-host'),
        'Querying the Water Point Data Exchange…', async function () {
          var raw = await C.fetchWaterPoints(spec.lat, spec.lon, spec.radiusM,
            { limit: spec.limit });
          /* the cap is on rows returned by the query, so it has to be judged
           * before any of them are filtered out */
          derived.waterPointsCapped = !!(spec.limit && raw.length >= spec.limit);
          var points = C.parseWpdxRecords(raw);
          if (spec.clip) {
            points = C.pointsWithin(points, spec.lat, spec.lon, spec.radiusM);
          }
          derived.waterPoints = points;
          derived.waterPointsSource = spec.label;
          S.toast(points.length
            ? S.thousands(points.length) + ' water points read from WPdx+.'
            : 'WPdx+ has no mapped water point in that area.',
          points.length ? 'ok' : 'warn');
        });
    } catch (e) {
      S.toast(e.message + ' The CSV upload works offline.', 'error');
    }
    render();
  }

  function waterPointSourceNote() {
    var points = derived.waterPoints || [];
    if (!points.length) return null;
    return el('p.muted', [
      S.thousands(points.length) + ' water points loaded' +
      (derived.waterPointsSource ? ' (' + derived.waterPointsSource + ')' : '') +
      '. ' + C.WPDX_CREDIT,
    ]);
  }

  PAGES.waterpoints = function () {
    var latlon = siteLatLon();
    var points = derived.waterPoints || [];
    var radius = store.get('waterpoints.radius', C.DEFAULT_SEARCH_RADIUS_M);
    var nodes = [
      pageHead('Water points', 'Before drilling a new borehole, check what is ' +
        'already there. A broken improved source nearby is usually cheaper to ' +
        'rehabilitate; a working one inside the service radius may already serve ' +
        'the community.'),
      card('Water point inventory', [
        el('p.muted', 'Look the area up live in the Water Point Data Exchange ' +
          '(WPdx+), or upload an export as CSV. The lookup is the only request ' +
          'this application ever makes; everything else runs offline, and a ' +
          'CSV brought in the field needs no connection at all.'),
        field('Search radius around the site (m)',
          S.numberInput(radius, function (value) {
            store.set('waterpoints.radius',
              S.clamp(Number(value) || C.DEFAULT_SEARCH_RADIUS_M, 100, 25000));
            render();
          }, { min: 100, max: 25000, step: 250 }),
          'Existing working sources inside ' + Math.round(C.SERVICE_RADIUS_M) +
          ' m are treated as already serving the site.'),
        el('div.btn-row', [
          button('Look up water points', function (event) {
            if (!latlon) {
              S.toast('Enter the site GPS position on the Site page first.', 'warn');
              return;
            }
            lookUpWaterPoints(event.target, {
              lat: latlon.lat, lon: latlon.lon, radiusM: radius, limit: 5000,
              clip: true,
              label: 'live WPdx+, ' + Math.round(radius) + ' m around the site',
            });
          }, { disabled: !latlon,
            title: latlon ? 'Query WPdx+ for this site'
              : 'Needs the site GPS position' }),
          button('Upload WPdx CSV', async function () {
            var file = await S.pickFile('.csv,text/csv');
            if (!file) return;
            try {
              var text = await S.readFile(file, 'text');
              derived.waterPoints = C.parseWpdxRecords(S.parseCsv(text));
              derived.waterPointsSource = file.name;
              derived.waterPointsCapped = false;
              S.toast(derived.waterPoints.length + ' water points read.', 'ok');
              render();
            } catch (e) {
              S.toast('Could not read that CSV: ' + e.message, 'error');
            }
          }, { variant: 'ghost' }),
          points.length ? button('Clear', function () {
            derived.waterPoints = null; derived.waterPointsSource = null;
            derived.waterPointsCapped = false; render();
          }, { variant: 'ghost' }) : null,
        ]),
        !latlon ? el('p.muted', 'The live lookup needs the site GPS position; ' +
          'set it on the Site page. A CSV export can be analysed without one.') : null,
        derived.waterPointsCapped ? el('div.callout.callout-warn', el('p',
          'The lookup hit its row cap, so this is a partial slice of the area. ' +
          'Narrow the radius, or use a filtered CSV export for a complete, ' +
          'reproducible analysis.')) : null,
        waterPointSourceNote(),
      ]),
    ];

    if (!points.length) return nodes;

    var summary = C.functionalitySummary(points);
    nodes.push(card('Functionality', [
      S.statRow([
        S.stat('Total mapped', S.thousands(summary.total)),
        S.stat('Functional', S.thousands(summary.functional)),
        S.stat('Non-functional', S.thousands(summary.non_functional)),
        S.stat('Functional rate', summary.functional_rate !== null
          ? summary.functional_rate.toFixed(0) + '%' : '—',
          summary.unknown + ' of unknown status'),
      ]),
    ]));

    if (latlon) {
      var decision = C.rehabVsDrill(points, latlon.lat, latlon.lon,
        { searchRadiusM: radius });
      var tone = decision.recommendation === C.DRILL_NEW ? '.callout-ok'
        : (decision.recommendation === C.ASSESS_REHAB ? '.callout-warn' : '.callout');
      var pointColumns = [
        { key: 'distance_m', label: 'Distance (m)', align: 'right',
          format: function (v) { return Math.round(v); } },
        { key: 'source', label: 'Source' },
        { key: 'technology', label: 'Technology' },
        { key: 'status_text', label: 'Status' },
        { key: 'functional', label: 'Functional',
          format: function (v) {
            return S.badge(v === true ? 'yes' : (v === false ? 'no' : 'unknown'),
              v === true ? 'ok' : (v === false ? 'bad' : null));
          } },
        { key: 'improved', label: 'Improved',
          format: function (v) { return v ? 'yes' : 'no'; } },
        { key: 'installed', label: 'Installed', align: 'right' },
      ];
      nodes.push(card('Rehabilitate or drill?', [
        el('div.callout' + tone, [
          el('p', el('strong', decision.headline)),
          el('p', decision.rationale),
        ]),
        charts.figure(charts.siteMap({
          context: (GWT.data.geo.chiefdomBoundaries || {}).features || [],
          points: decision.nearby.slice(0, 200).map(function (p) {
            return {
              lon: p.lon, lat: p.lat,
              colour: p.functional === true ? charts.palette().good
                : (p.functional === false ? charts.palette().critical
                  : charts.palette().muted),
              size: 3.5,
            };
          }).concat([{
            lon: latlon.lon, lat: latlon.lat, kind: 'diamond',
            colour: charts.palette().accent, size: 7, label: 'Proposed site',
          }]),
          title: 'Water points near the site',
          legendItems: [
            { label: 'Functional', colour: charts.palette().good },
            { label: 'Non-functional', colour: charts.palette().critical },
            { label: 'Unknown', colour: charts.palette().muted },
            { label: 'Proposed site', colour: charts.palette().accent, kind: 'diamond' },
          ],
          width: 640, height: 520,
        }), 'Mapped water points around the proposed site',
          { filename: 'water_points' }),
      ]));

      if (decision.rehab_candidates.length) {
        nodes.push(card('Rehabilitation candidates', [
          el('p.muted', 'Broken improved sources inside the search radius, ' +
            'nearest first. Assess why each failed before committing to a new ' +
            'borehole: a failed pump is usually worth rehabilitating, a dry or ' +
            'collapsed hole is not.'),
          S.table(pointColumns, decision.rehab_candidates.slice(0, 30)),
        ]));
      }

      nodes.push(card('All water points in range', [
        decision.nearby.length
          ? S.table(pointColumns, decision.nearby.slice(0, 100))
          : S.empty('Nothing mapped within ' + Math.round(radius) + ' m of the site.'),
        decision.nearby.length > 100
          ? el('p.muted', 'Showing the nearest 100 of ' +
            S.thousands(decision.nearby.length) + '.') : null,
      ]));
    } else {
      nodes.push(S.empty('Enter the site GPS position on the Site page to get a ' +
        'rehabilitate-or-drill recommendation.',
        button('Site & maps', function () { goto('site'); }, { variant: 'ghost' })));
    }
    nodes.push(nextStep('The same inventory ranks whole districts by people ' +
      'per functional water point.', 'Coverage gap', 'coverage'));
    return nodes;
  };

  /* --- coverage gap --------------------------------------------------------- */

  var COVERAGE_LIMIT = 200000;

  PAGES.coverage = function () {
    var level = store.get('coverage.level', 'district');
    var points = derived.waterPoints || [];
    var nodes = [
      pageHead('Coverage gap', 'Where the next borehole does the most good: ' +
        'population per functional water point, by district or by chiefdom, ' +
        'joining the 2015 census with the water point inventory.'),
      card('Resolution', [
        el('div.chips', [
          el('button.chip' + (level === 'district' ? '.active' : ''), {
            type: 'button', onclick: function () { store.set('coverage.level', 'district'); render(); },
          }, 'District'),
          el('button.chip' + (level === 'chiefdom' ? '.active' : ''), {
            type: 'button', onclick: function () { store.set('coverage.level', 'chiefdom'); render(); },
          }, 'Chiefdom'),
        ]),
        waterPointSourceNote() || el('p.muted',
          'Coverage needs a national or regional water point inventory. Fetch ' +
          'one from WPdx+, or upload a CSV export on the Water points page.'),
        el('div.btn-row', [
          button('Fetch national water points', function (event) {
            /* a bounding box around the country's centre; the cap is high
             * because a national pull - plus the box's Guinea and Liberia
             * fringe, which the chiefdom join discards - is tens of thousands
             * of points */
            lookUpWaterPoints(event.target, {
              lat: 8.46, lon: -11.79, radiusM: 300000.0, limit: COVERAGE_LIMIT,
              clip: false,
              label: 'live WPdx+, national',
            });
          }),
          button('Water points page', function () { goto('waterpoints'); },
            { variant: 'ghost' }),
          points.length ? button('Clear', function () {
            derived.waterPoints = null; derived.waterPointsSource = null;
            derived.waterPointsCapped = false; render();
          }, { variant: 'ghost' }) : null,
        ]),
        derived.waterPointsCapped ? el('div.callout.callout-warn', el('p',
          'The national pull hit the ' + S.thousands(COVERAGE_LIMIT) +
          '-row cap, so the ranking may be partial. Prefer a filtered WPdx CSV ' +
          'export for a complete, reproducible analysis.')) : null,
      ]),
    ];
    if (!points.length) return nodes;

    var polys = polygons();
    var chiefdomDistrict = C.loadChiefdomDistrict();
    var rows, features, valueFor, nameFor, title;

    if (level === 'district') {
      var counted = C.countPointsByDistrict(points, polys, chiefdomDistrict);
      rows = C.coverageRows(C.loadDistrictPopulation(), counted.counts);
      var byDistrict = {};
      rows.forEach(function (r) { byDistrict[r.name] = r.people_per_point; });
      features = (GWT.data.geo.chiefdomBoundaries || {}).features || [];
      valueFor = function (feature) {
        var name = (feature.properties || {}).name;
        var district = chiefdomDistrict[name];
        var v = byDistrict[district];
        return v === null || v === undefined ? null : v;
      };
      nameFor = function (feature) { return (feature.properties || {}).name; };
      title = 'People per functional water point, by district';
    } else {
      var pop = C.chiefdomPopulation();
      var counts = C.countPointsByChiefdom(points, polys);
      rows = C.chiefdomCoverageRows(pop.population, counts.counts, chiefdomDistrict);
      var byChiefdom = {};
      rows.forEach(function (r) { byChiefdom[r.name] = r.people_per_point; });
      features = (GWT.data.geo.chiefdomBoundaries || {}).features || [];
      valueFor = function (feature) {
        var v = byChiefdom[(feature.properties || {}).name];
        return v === null || v === undefined ? null : v;
      };
      nameFor = function (feature) { return (feature.properties || {}).name; };
      title = 'People per functional water point, by chiefdom';
    }

    var stats = C.coverageStats(rows);
    nodes.push(card('Headline', [
      S.statRow([
        S.stat('Areas', String(stats.n_areas)),
        S.stat('With no functional source', String(stats.n_no_source),
          'ranked worst by definition'),
        S.stat('Worst measurable', stats.worst_served_people_per_point
          ? S.thousands(Math.round(stats.worst_served_people_per_point)) : '—',
          stats.worst_served_area || ''),
        S.stat('National average', stats.national_people_per_point
          ? S.thousands(Math.round(stats.national_people_per_point)) : '—',
          'people per functional point'),
      ]),
      charts.figure(charts.choropleth({
        features: features, value: valueFor, name: nameFor,
        title: title, legendTitle: 'people per functional water point',
        width: 640, height: 600,
      }), title, { filename: 'coverage_' + level }),
      el('p.muted', C.POPULATION_CREDIT + ' ' + C.WPDX_CREDIT),
    ]));

    nodes.push(card('Ranked need', [
      S.table([
        { key: 'rank', label: 'Rank', align: 'right' },
        { key: 'name', label: level === 'district' ? 'District' : 'Chiefdom' },
        level === 'chiefdom' ? { key: 'district', label: 'District' } : null,
        { key: 'population', label: 'Population', align: 'right',
          format: function (v) { return S.thousands(Math.round(v)); } },
        { key: 'water_points', label: 'Mapped points', align: 'right' },
        { key: 'functional_points', label: 'Functional', align: 'right' },
        { key: 'people_per_point', label: 'People per point', align: 'right',
          format: function (v) {
            return v === null ? 'no functional source' : S.thousands(Math.round(v));
          } },
      ].filter(Boolean), rows.slice(0, 60), {
        rowClass: function (row) {
          return row.functional_points === 0 ? 'row-bad'
            : (row.rank <= 5 ? 'row-warn' : '');
        },
      }),
    ]));
    return nodes;
  };

  /* --- portfolio ------------------------------------------------------------ */

  /* A saved project, whichever of the two applications wrote it.
   *
   * The browser app saves JSON and the Streamlit app saves YAML, but both
   * carry the same headline ``summary`` block, so a programme can pool files
   * from both. An older file without a summary falls back to its site inputs,
   * which is all the map and the status column need. */
  function summaryFromProjectFile(name, text) {
    var payload;
    if (/\.ya?ml$/i.test(name)) {
      payload = S.parseYaml(text);
    } else {
      payload = JSON.parse(text);
    }
    if (!payload || typeof payload !== 'object') throw new Error('not a project file');
    var summary = payload.summary;
    if (summary && typeof summary === 'object' && Object.keys(summary).length) {
      return summary;
    }
    var state = payload.state;
    if (!state || typeof state !== 'object') throw new Error('not a project file');
    if (state.site) {                                   /* browser project file */
      return {
        community: state.site.community, district: state.site.district,
        chiefdom: state.site.chiefdom, easting: state.site.easting,
        northing: state.site.northing, utm_zone: state.site.utm_zone,
      };
    }
    return {                                          /* Streamlit project file */
      community: state.meta_community, district: state.meta_district,
      chiefdom: state.meta_chiefdom, easting: state.meta_easting,
      northing: state.meta_northing,
      utm_zone: Number(String(state.meta_zone || '29N').replace(/N$/i, '')) || 29,
    };
  }

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
   * deciding it is, on a day, not by opening a page. */
  function currentAsset() {
    var stored = store.get('asset');
    var record = stored ? C.assetFromDict(stored) : null;
    if (record) return record;
    return C.assetFromProject(projectState());
  }

  function saveAsset(asset) {
    store.set('asset', asset);
    render();
  }

  PAGES.registry = function () {
    var asset = currentAsset();
    var nodes = [
      pageHead('Asset registry', 'A drilling project ends; the borehole does ' +
        'not. This page holds the other half: a stable identifier that ' +
        'outlives the project file, the maintenance history recorded against ' +
        'it, and what that history says is true today. Nothing here is ' +
        'assumed — a borehole nobody has reported on is not working, it is ' +
        'unknown.'),
    ];

    if (!asset) {
      nodes.push(card('This borehole', [
        el('div.callout.callout-warn', el('p', 'This project has no recorded ' +
          'position yet, so it cannot be given an identifier — there would be ' +
          'nothing to find the borehole by. Enter the GPS position on the ' +
          'Site page.')),
        el('div.btn-row', [button('Go to the site page', function () {
          goto('site');
        }, { variant: 'ghost' })]),
      ]));
    } else {
      var state = C.assetState(asset);
      var tone = state.function === 'functional' ? 'ok'
        : (state.function === 'non_functional' ? 'bad' : 'warn');
      var outstanding = state.due.filter(function (item) {
        return item.state === 'overdue' || item.state === 'unknown';
      });
      nodes.push(card('This borehole', [
        el('p.asset-id', asset.asset_id),
        el('p.muted', 'The identifier is derived from the position, so two ' +
          'teams at the same wellhead with no connection between them arrive ' +
          'at the same one. The last character is a check character: it ' +
          'catches every single mistyped character and every transposition ' +
          'of two adjacent ones.'),
        S.statRow([
          S.stat('Status', state.label),
          S.stat('Last inspected', state.last_inspection || 'never'),
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
      ]));

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

      if ((asset.events || []).length) {
        nodes.push(card('History', [
          S.table(['Date', 'Event', 'Note', 'Recorded by'],
            asset.events.map(function (e) {
              return [e.when || '(no date)', C.eventLabel(e.kind), e.note || '',
                e.by || ''];
            })),
        ]));
      }

      nodes.push(card('For the headworks', [
        el('p.muted', 'The plate carries the identifier, the symbol that ' +
          'encodes it and the facts that do not go out of date. The symbol ' +
          'holds the details themselves rather than a link, because the ' +
          'reason it is on the borehole is that there is no network there.'),
        el('div.qr-preview', {
          html: C.qrSvg(C.qrEncode(C.qrPayload(asset), { ecc: 'H' }),
            { scale: 3, border: 4 }),
        }),
        el('div.btn-row', [
          button('Identification plate (.docx)', async function (event) {
            await buildAssetDoc('placard', asset, event.target);
          }),
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
        { placeholder: 'SL-WAR-8FEEVKQ-T' }), ''),
      lookupResult(store.get('registry.lookup', '')),
    ]));

    nodes.push(registryCard());
    return nodes;
  };

  function lookupResult(typed) {
    if (!typed) return null;
    var verdict = C.validateAssetId(typed);
    return el('div.callout.callout-' + (verdict.ok ? 'ok' : 'bad'),
      el('p', verdict.ok
        ? 'That is a valid identifier: ' + verdict.assetId
        : verdict.reason));
  }

  function registryCard() {
    var assets = derived.registry || [];
    var nodes = [
      el('p.muted', 'Drop in saved project files to see the whole register: ' +
        'what is working, what is not, and what is overdue a visit. A file ' +
        'only carries an asset record once its borehole has an identifier.'),
      el('div.btn-row', [
        button('Add project files', async function () {
          var list = await S.pickFile('.json,.gwt,.yaml,.yml', true);
          if (!list || !list.length) return;
          var loaded = (derived.registry || []).slice();
          var skipped = 0;
          for (var i = 0; i < list.length; i++) {
            try {
              var text = await S.readFile(list[i], 'text');
              var record = assetFromProjectFile(list[i].name, text);
              if (record) loaded.push(record); else skipped += 1;
            } catch (e) { skipped += 1; }
          }
          derived.registry = loaded;
          S.toast(loaded.length + ' ' + S.plural(loaded.length, 'borehole') +
            ' in the register' + (skipped ? ', ' + skipped + ' skipped' : '') + '.',
          skipped ? 'warn' : 'ok');
          render();
        }),
        assets.length ? button('Clear', function () {
          derived.registry = [];
          render();
        }, { variant: 'ghost' }) : null,
      ].filter(Boolean)),
    ];
    if (!assets.length) {
      nodes.push(el('p.muted', 'Nothing loaded yet.'));
      return card('Many boreholes', nodes);
    }
    var stats = C.registryStats(assets);
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
        ' borehole(s) have nothing recorded against them at all. That is not ' +
        'the same as nothing having happened to them.')));
    }
    if (stats.n_overdue_inspection + stats.n_overdue_sample) {
      nodes.push(el('p', stats.n_overdue_inspection + ' overdue a sanitary ' +
        'inspection, ' + stats.n_overdue_sample + ' overdue a water quality ' +
        'sample.'));
    }
    var rows = C.registryRows(assets);
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

  async function buildAssetDoc(kind, asset, node) {
    var host = node ? node.closest('.card') : $('#page-host');
    try {
      await S.withBusy(host, 'Building the document…', async function () {
        var cfg = config();
        var context = {
          style: cfg.style, asset: asset, state: C.assetState(asset),
          readiness: reportReadiness('completion'),
          symbol: qrDataUrl(C.qrPayload(asset), { ecc: 'H', scale: 8 }),
        };
        var builder = kind === 'placard'
          ? await GWT.docx.assetPlacard(context)
          : await GWT.docx.assetRecordReport(context);
        var bytes = await builder.build();
        S.download((kind === 'placard' ? 'placard_' : 'asset_') +
          asset.asset_id + '.docx', bytes);
      });
      S.toast('Document ready.', 'ok');
    } catch (err) {
      S.toast('Could not build the document: ' + err.message, 'bad');
    }
  }

  PAGES.portfolio = function () {
    var summaries = derived.portfolio || [];
    var chosenIndex = Math.min(store.get('portfolio.site', 0), Math.max(summaries.length - 1, 0));

    var nodes = [
      pageHead('Portfolio', 'Many boreholes side by side. Save a project from ' +
        'any page — each file carries a short summary — then drop several of ' +
        'them here for a status map, a comparison table and the headline ' +
        'figures a water manager needs.'),
      card('Saved projects', [
        el('p.muted', 'Project files from this app (.gwt.json) and from the ' +
          'Streamlit app (.yaml) both work, so a programme run across the two ' +
          'still pools into one view.'),
        el('div.btn-row', [
          button('Add project files', async function () {
            var list = await S.pickFile('.json,.gwt,.yaml,.yml', true);
            if (!list || !list.length) return;
            var loaded = derived.portfolio ? derived.portfolio.slice() : [];
            var skipped = 0;
            for (var i = 0; i < list.length; i++) {
              try {
                var text = await S.readFile(list[i], 'text');
                loaded.push(summaryFromProjectFile(list[i].name, text));
              } catch (e) { skipped += 1; }
            }
            derived.portfolio = loaded;
            S.toast(loaded.length + ' ' + S.plural(loaded.length, 'project') +
              ' loaded' + (skipped ? ', ' + skipped + ' skipped' : '') + '.',
            skipped ? 'warn' : 'ok');
            render();
          }),
          summaries.length ? button('Add this project', function () {
            derived.portfolio = (derived.portfolio || []).concat([projectSummary()]);
            render();
          }, { variant: 'ghost' }) : null,
          summaries.length ? button('Clear', function () {
            derived.portfolio = null; render();
          }, { variant: 'ghost' }) : null,
        ]),
        !summaries.length ? el('p.muted', 'Nothing loaded yet. You can also ' +
          'start with the project open in this window:') : null,
        !summaries.length ? button('Start from the open project', function () {
          derived.portfolio = [projectSummary()];
          render();
        }, { variant: 'ghost' }) : null,
      ]),
    ];

    if (!summaries.length) {
      nodes.push(S.empty('Load two or more saved project files to build the ' +
        'portfolio: a status map, a comparison table and the programme figures.'));
      return nodes;
    }

    var stats = C.portfolioStats(summaries);
    nodes.push(card('Programme', [
      S.statRow([
        S.stat('Projects', String(stats.n_projects)),
        S.stat('Successful', String(stats.n_successful),
          'of ' + stats.n_drilled + ' drilled'),
        S.stat('Success rate', stats.success_rate !== null
          ? stats.success_rate.toFixed(0) + '%' : '—', 'over drilled holes'),
        S.stat('Mean safe yield', stats.mean_safe_yield_m3_per_h !== null
          ? stats.mean_safe_yield_m3_per_h.toFixed(2) + ' m³/h' : '—'),
        S.stat('Mean cost/m', stats.mean_cost_per_meter_usd !== null
          ? S.money(stats.mean_cost_per_meter_usd, 0) : '—'),
      ]),
      /* Three rates, not one. A single "safe to drink" tile counted an
       * aesthetic exceedance as safe and hid national-standard failures
       * inside it, so a breached programme showed 100%. */
      S.statRow([
        S.stat('Water compliant', stats.wq_compliant_rate !== null
          ? stats.wq_compliant_rate.toFixed(0) + '%' : '—',
          'of ' + stats.n_wq_assessed + ' sampled: meets every health and ' +
          'national limit'),
        S.stat('Water failing', stats.wq_fail_rate !== null
          ? stats.wq_fail_rate.toFixed(0) + '%' : '—',
          'exceeds a health guideline or a national limit'),
        S.stat('Water unproven', stats.wq_unproven_rate !== null
          ? stats.wq_unproven_rate.toFixed(0) + '%' : '—',
          'results incomplete or not evaluable'),
      ]),
      stats.n_status_unrecognised
        ? el('div.callout.callout-warn', el('p', stats.n_status_unrecognised +
          ' project(s) carry a status this toolkit does not recognise; they ' +
          'are counted as neither successful nor dry. Correct the status on ' +
          'the drilling log.'))
        : null,
    ].filter(Boolean)));

    var points = C.portfolioPoints(summaries);
    nodes.push(card('Where they are', [
      points.length ? charts.figure(charts.siteMap({
        context: (GWT.data.geo.adminBoundaries || {}).features || [],
        points: points.map(function (p) {
          return {
            lon: p.lon, lat: p.lat, label: p.label, size: 5.5,
            colour: C.STATUS_COLORS[p.status],
          };
        }),
        title: 'Borehole portfolio',
        legendItems: Object.keys(C.STATUS_LABELS).map(function (key) {
          return { label: C.STATUS_LABELS[key], colour: C.STATUS_COLORS[key] };
        }),
        width: 640, height: 560,
      }), 'Project status by location', { filename: 'portfolio_map' })
        : S.empty('Add GPS coordinates to the projects to place them on the map.'),
    ]));

    nodes.push(card('Comparison', [
      S.table([
        { key: 'Community', label: 'Community' },
        { key: 'District', label: 'District' },
        { key: 'Status', label: 'Status' },
        { key: 'Depth (m)', label: 'Depth (m)', align: 'right' },
        { key: 'Safe yield (m3/h)', label: 'Safe yield (m³/h)', align: 'right' },
        { key: 'Water', label: 'Water' },
        { key: 'Cost/m (USD)', label: 'Cost/m (USD)', align: 'right' },
      ], C.portfolioRows(summaries), {
        rowClass: function (row, i) {
          return C.classifyStatus(summaries[i]) === 'dry' ? 'row-bad' : '';
        },
      }),
    ]));

    var chosen = summaries[chosenIndex];
    nodes.push(card('Site detail', [
      el('p.muted', 'Drill into one site for its full record and a one-page brief.'),
      field('Site', S.selectInput(String(chosenIndex),
        summaries.map(function (s, i) {
          return { value: String(i), label: C.portfolioSiteLabel(s, i) };
        }), function (value) {
          store.set('portfolio.site', Number(value)); render();
        })),
      S.table([
        { key: '0', label: 'Field' },
        { key: '1', label: 'Value' },
      ], C.portfolioSiteDetail(chosen)),
      el('div.btn-row', [
        button('Download site brief (.txt)', function () {
          var name = String(chosen.community || 'site').trim().replace(/\s+/g, '_');
          S.download(name + '_brief.txt', C.portfolioOnePager(chosen), 'text/plain');
        }),
      ]),
    ]));
    return nodes;
  };

  /* --- settings ------------------------------------------------------------- */

  PAGES.settings = function () {
    var cfg = config();
    var overrides = store.get('config') || {};
    function bindCfg(section, key) {
      return function (value) {
        store.set('config.' + section + '.' + key, value);
        recompute().then(function () { runInversions({ quiet: true }).then(render); });
      };
    }
    function numberFields(section, keys) {
      return keys.map(function (spec) {
        return field(spec[1], S.numberInput(cfg[section][spec[0]],
          bindCfg(section, spec[0]), { step: 'any' }), spec[2]);
      });
    }

    return [
      pageHead('Settings', 'House style, interpretation thresholds and design ' +
        'rules. Every value is a project override of the toolkit default, so a ' +
        'client with different standards changes them here rather than in code.'),

      card('House style (reports and figures)', [
        el('div.field-row', [
          field('Organisation', S.textInput(cfg.style.organisation, function (v) {
            store.set('config.style.organisation', v); render();
          })),
          field('Organisation details', S.textInput(cfg.style.organisation_details,
            function (v) { store.set('config.style.organisation_details', v); render(); })),
          field('Report font', S.textInput(cfg.style.font_name, function (v) {
            store.set('config.style.font_name', v); render();
          })),
          field('Accent colour', S.textInput(cfg.style.accent_color, function (v) {
            store.set('config.style.accent_color', v); render();
          }), 'used for headings and table header rows'),
        ]),
      ]),

      card('VES interpretation thresholds (ohm-m)', [
        el('div.field-row', numberFields('ves', [
          ['fresh_basement_min_rho', 'Fresh basement, minimum'],
          ['laterite_min_rho', 'Dry laterite, minimum'],
          ['clay_max_rho', 'Clay, maximum'],
          ['max_layers', 'Maximum layers searched'],
          ['target_fit_percent', 'Target fit error (%)'],
          ['round_drilling_depth_to_m', 'Round drilling depth to (m)'],
        ])),
        el('p.muted', 'The defaults target crystalline basement terrain. Coastal ' +
          'sedimentary sites need different ranges.'),
      ]),

      card('Pumping test defaults', [
        el('div.field-row', numberFields('pumping', [
          ['safety_factor', 'Safety factor'],
          ['design_period_days', 'Design period (days)'],
          ['available_drawdown_fraction', 'Usable share of available drawdown'],
          ['pump_submergence_min_m', 'Minimum submergence (m)'],
          ['seasonal_allowance_m', 'Dry season decline allowance (m)'],
          ['cooper_jacob_u_max', 'Cooper-Jacob u limit'],
        ])),
      ]),

      card('Borehole design rules', [
        el('div.field-row', numberFields('design', [
          ['borehole_diameter_in', 'Drilled diameter (in)'],
          ['casing_diameter_in', 'Casing diameter (in)'],
          ['screen_slot_mm', 'Screen slot (mm)'],
          ['screen_length_default_m', 'Default screen length (m)'],
          ['sanitary_seal_depth_m', 'Sanitary seal depth (m)'],
          ['gravel_pack_above_top_screen_m', 'Gravel above top screen (m)'],
          ['sump_length_m', 'Sump length (m)'],
          ['stickup_m', 'Stick-up (m)'],
          ['min_screen_below_swl_m', 'Minimum screen depth below SWL (m)'],
        ])),
      ]),

      card('AI assisted extraction', [
        el('p.muted', 'Reading a photographed field sheet needs a model, and ' +
          'there is no server here to hold a key on your behalf. Paste an ' +
          'Anthropic API key to enable it on the Scanned sheets page.'),
        field('Anthropic API key',
          S.textInput(getApiKey(), function (value) {
            setApiKey(value, credential.remember);
            render();
          }, { type: 'password', autocomplete: 'off', spellcheck: 'false',
            placeholder: 'sk-ant-…' }),
          'Held for this tab only. It is never saved with your project and ' +
          'never written to this browser\'s long-term storage.'),
        S.checkboxInput(credential.remember,
          'Keep it for this tab (cleared when the tab closes). Leave ' +
          'unticked to hold it in memory only, so a page reload asks again.',
          function (checked) {
            setApiKey(getApiKey(), checked);
            render();
          }),
        field('Model',
          S.textInput(store.get('extraction.model') || '', function (value) {
            store.set('extraction.model', String(value).trim());
          }, { placeholder: C.EXTRACTION_MODEL }),
          'Leave blank for ' + C.EXTRACTION_MODEL + '.'),
        el('div.callout.callout-warn', el('p', [
          el('strong', 'A key in a browser is a key you have exposed. '),
          'The request goes from this page straight to api.anthropic.com, so ' +
          'the key is visible to anything running in this page. It is held ' +
          'for this tab only — never in long-term storage, never in a saved ' +
          'project file, never cached by the offline worker — but that ' +
          'removes durability, not exposure. Use a key scoped to this work ' +
          'and revoke it when the job is done. Every other page works ' +
          'without one. If you need this at scale, put the call behind your ' +
          'own server and keep the key there.',
        ])),
        getApiKey() ? el('div.btn-row', [
          button('Forget the key', function () {
            forgetApiKey();
            S.toast('The key was removed from this browser.', 'ok');
            render();
          }, { variant: 'ghost' }),
        ]) : null,
      ]),

      card('Project data', [
        el('div.btn-row', [
          button('Save project file', saveProject),
          button('Open project file', openProject, { variant: 'ghost' }),
          button('Reset everything', function () {
            S.modal('Reset the workspace?', el('p',
              'This clears the site details, the uploaded sheets, every result ' +
              'and the saved copy in this browser. Save the project first if you ' +
              'want to keep it.'), [
              button('Reset', function () {
                store.forget();
                forgetApiKey();
                store.replace(blankState());
                Object.keys(derived).forEach(function (k) { derived[k] = null; });
                applyTheme(); renderChrome(); render();
                S.toast('Workspace reset.', 'ok');
                document.querySelectorAll('.modal-overlay').forEach(function (n) {
                  n.parentNode.removeChild(n);
                });
              }, { variant: 'danger' }),
            ]);
          }, { variant: 'ghost' }),
        ]),
        el('p.muted', 'The working session is mirrored into this browser\'s local ' +
          'storage so a refresh never loses fieldwork. The project file is the ' +
          'record you keep and share.'),
      ]),
    ];
  };

  /* --- about ---------------------------------------------------------------- */

  PAGES.about = function () {
    return [
      pageHead('About & method', 'What this app computes, what it assumes, and ' +
        'where the numbers come from.'),
      card('What it is', [
        el('p', 'A standalone version of the Groundwater Investigation Toolkit ' +
          'for rural water supply boreholes in Sierra Leone. It covers the whole ' +
          'project lifecycle — geophysical siting, borehole design, drilling ' +
          'records, pumping tests, water quality, costing, supervision and ' +
          'handover — and produces client-ready Word reports.'),
        el('p', 'Everything runs in this browser. Uploaded field sheets are ' +
          'parsed in the page, the analyses run in the page, and the reports are ' +
          'assembled in the page. No data is sent to any server, which is what ' +
          'makes it usable on a field laptop with an intermittent connection.'),
        el('p', 'Two features are the exception, and both are a button you ' +
          'press rather than something the page does on its own: looking up ' +
          'existing water points asks the Water Point Data Exchange, and the ' +
          'AI-assisted reading of a photographed field sheet sends that sheet ' +
          'to Anthropic under a key you supply. Everything else works with the ' +
          'network cable pulled out, including the CSV path for water points.'),
      ]),
      card('Methods', [
        el('h4', 'Geophysics'),
        el('p', 'Apparent resistivity comes from the measured resistance and the ' +
          'array geometric factor. The layered-earth forward model evaluates the ' +
          'Hankel transform of the Koefoed resistivity transform by direct ' +
          'Gauss-Legendre quadrature — no tabulated filter coefficients — and the ' +
          'inversion is damped least squares on the logarithms of resistivity and ' +
          'thickness. The reported fit error matches the IPI2Win ERR quantity.'),
        el('h4', 'Hydraulics'),
        el('p', 'Cooper-Jacob on the late-time straight line with the u < 0.05 ' +
          'validity check, a Theis type-curve fit, Theis recovery on residual ' +
          'drawdown, and Hantush-Bierschenk for step tests. The safe yield ' +
          'projects drawdown to the design period and applies the stated safety ' +
          'factor; it is reported as a range across the assumptions it rests on, ' +
          'because storativity and the effective well radius are not resolvable ' +
          'from a single pumped well.'),
        el('h4', 'Water quality'),
        el('p', 'Results are compared against WHO guideline values and the ' +
          'national standard, with the combined nitrate and nitrite rule applied. ' +
          'The charge balance checks the analysis itself. Corrosivity uses the ' +
          'Langelier, Ryznar, Aggressive and Larson-Skold indices and produces a ' +
          'rising-main materials recommendation.'),
        el('h4', 'Costing'),
        el('p', 'The RWSN Borehole Costing Model: line items by stage and by ' +
          "resource category, the contractor's cost separated from the client's " +
          'price, and a programme estimate that lets the successful boreholes ' +
          'carry the expected dry attempts.'),
      ]),
      card('Data sources', [
        el('ul', [
          el('li', 'WHO Guidelines for Drinking-water Quality, 4th edition with addenda.'),
          el('li', 'RWSN/Skat Cost-Effective Boreholes, and "Costing and Pricing: ' +
            'a Guide for Water Well Drilling Enterprises".'),
          el('li', 'RWSN/UNICEF "Supervising Water Well Drilling" and ' +
            '"Professional Water Well Drilling".'),
          el('li', 'geoBoundaries administrative boundaries (CC BY 4.0).'),
          el('li', 'BGS Africa Groundwater Atlas hydrogeology of Sierra Leone (CC BY-SA 4.0).'),
          el('li', 'USGS Geologic Map of Africa.'),
          el('li', '2015 Population and Housing Census, Statistics Sierra Leone.'),
          el('li', 'Water Point Data Exchange (WPdx+), CC BY 4.0 — user supplied.'),
        ]),
        el('p.muted', 'The guideline table, the rate catalogue, the checklists ' +
          'and the separation distances are editable data files in the ' +
          'repository, so field practice can be adapted without code changes.'),
      ]),
      card('Limitations', [
        el('ul', [
          el('li', 'Resistivity models are not unique: different layer ' +
            'combinations can fit one curve almost equally well, and the depth of ' +
            'investigation is limited by the maximum electrode spacing. Only ' +
            'drilling confirms the section.'),
          el('li', 'Storativity from a single pumped well is an assumption, not ' +
            'a measurement.'),
          el('li', 'A water quality analysis describes one sample at one moment; ' +
            'microbiological quality in particular varies with season.'),
          el('li', 'Unit rates are indicative and must be confirmed locally ' +
            'before use in a tender.'),
        ]),
      ]),
      card('Also available', [
        el('p', ['This app carries every page the Streamlit version has — ' +
          'including the Depth Spine, the Portfolio and the scanned-sheet ' +
          'reader — and its engine is held to the Python package\'s own ' +
          'numbers by a parity check that runs on the real sample workbooks.']),
        el('p', ['Two things read differently rather than less. The PDF ' +
          'text-layer reader here works from the layout of the words on the ' +
          'page; the server version uses pdfplumber, which finds a table from ' +
          'the rules drawn around it. And the sign-off ledger on the Depth ' +
          'Spine is kept in the project file rather than in a session.']),
        el('p', ['A WebAssembly build of the Streamlit app is published ' +
          'beside this one — it runs the real Python package in the browser, ' +
          'at the cost of a 60 MB first load.']),
        el('p', el('a', { href: 'wasm/', target: '_blank', rel: 'noopener' },
          'Open the WebAssembly build →')),
      ]),
    ];
  };

  /* ------------------------------------------------------------ report cards */

  function photoCard(setName, title) {
    var values = store.get('photos.' + setName) || {};
    return card(title, [
      GWT.imageSlot.gallery(setName, values, function (next) {
        store.set('photos.' + setName, next);
      }),
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
      drilling_log: derived.log,
      pump_analysis: derived.analysis,
      wq_assessment: derived.assessment,
      borehole_design: derived.design,
      cost_estimate: derived.estimate,
    };
  }

  function reportReadiness(kind) {
    return C.assessReadiness(projectState(), kind,
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
          if (!why) {
            S.toast('An override needs a reason.', 'warn');
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

  function reportCard(title, kind, description, extra) {
    return card(title, [
      el('p.muted', description),
      readinessPanel(kind),
      el('div.btn-row', [
        button('Build ' + title + ' (.docx)', function (event) {
          buildReport(kind, extra, event.target);
        }),
      ]),
    ]);
  }

  async function buildReport(kind, extra, node) {
    var host = node ? node.closest('.card') : $('#page-host');
    try {
      await S.withBusy(host, 'Building the report…', async function () {
        var cfg = config();
        var context = {
          style: cfg.style, site: store.get('site'),
          signOff: signOffFor(kind),
          readiness: reportReadiness(kind),
        };
        if (kind === 'pumping' && derived.analysis) {
          context.seasonal = currentSeasonal(derived.analysis);
        }
        var builder;
        var figures = [];

        if (kind === 'geophysical') {
          if (!derived.interpretations || !derived.interpretations.length) {
            throw new Error('No sounding has been interpreted yet.');
          }
          for (var i = 0; i < derived.inversions.length; i++) {
            var result = derived.inversions[i];
            var id = derived.soundings[i].sounding_id;
            figures.push({
              soundingId: id,
              image: await charts.toPng(charts.vesCurve(result, { hover: false })),
              caption: 'Sounding curve and fitted model for ' + id,
            });
            figures.push({
              soundingId: id,
              image: await charts.toPng(charts.layeredModel(result.model)),
              caption: 'Layered earth model for ' + id, widthCm: 9,
            });
          }
          context.interpretations = derived.interpretations;
          context.figures = figures;
          context.preferredOrder = store.get('ves.preferredOrder');
          builder = await docx.geophysicalReport(context);

        } else if (kind === 'completion') {
          if (!derived.design) throw new Error('There is no borehole design yet.');
          figures.push({
            image: await charts.toPng(charts.boreholeDesign(derived.design, derived.log)),
            caption: 'Borehole construction design', widthCm: 12,
          });
          GWT.imageSlot.collect(store.get('photos.completion'), 'completion')
            .forEach(function (photo) {
              figures.push({ image: photo, caption: photo.caption, widthCm: 12 });
            });
          context.log = derived.log || {};
          context.design = derived.design;
          context.figures = figures;
          builder = await docx.completionReport(context);

        } else if (kind === 'pumping') {
          if (!derived.analysis) throw new Error('No pumping test has been analysed.');
          figures.push({
            image: await charts.toPng(charts.testOverview(derived.test,
              derived.analysis, { hover: false })),
            caption: 'Water level through the pumping and recovery phases',
          });
          var cjFig = charts.cooperJacob(derived.analysis, { hover: false });
          if (cjFig) figures.push({ image: await charts.toPng(cjFig),
            caption: 'Cooper-Jacob straight line fit' });
          var recFig = charts.recovery(derived.analysis, { hover: false });
          if (recFig) figures.push({ image: await charts.toPng(recFig),
            caption: 'Theis recovery analysis' });
          var stFig = charts.stepTest(derived.analysis);
          if (stFig) figures.push({ image: await charts.toPng(stFig),
            caption: 'Step drawdown analysis' });
          GWT.imageSlot.collect(store.get('photos.pumping'), 'pumping')
            .forEach(function (photo) {
              figures.push({ image: photo, caption: photo.caption, widthCm: 12 });
            });
          context.analysis = derived.analysis;
          context.figures = figures;
          builder = await docx.pumpingReport(context);

        } else if (kind === 'quality') {
          if (!derived.assessment) throw new Error('No water quality analysis loaded.');
          var piperFig = charts.piper([derived.sample]);
          if (piperFig) figures.push({ image: await charts.toPng(piperFig),
            caption: 'Piper trilinear diagram', widthCm: 13 });
          var stiffFig = charts.stiff(derived.sample);
          if (stiffFig) figures.push({ image: await charts.toPng(stiffFig),
            caption: 'Stiff diagram', widthCm: 11 });
          GWT.imageSlot.collect(store.get('photos.quality'), 'quality')
            .forEach(function (photo) {
              figures.push({ image: photo, caption: photo.caption, widthCm: 11 });
            });
          context.assessment = derived.assessment;
          context.figures = figures;
          builder = await docx.qualityReport(context);

        } else if (kind === 'costing') {
          if (!derived.estimate) throw new Error('There is no cost estimate yet.');
          figures.push({
            image: await charts.toPng(charts.costBreakdown(derived.estimate,
              { mode: 'stage' })),
            caption: 'Direct cost by construction stage',
          });
          figures.push({
            image: await charts.toPng(charts.costBreakdown(derived.estimate,
              { mode: 'category' })),
            caption: 'Direct cost by resource category',
          });
          if (derived.programme) {
            figures.push({
              image: await charts.toPng(charts.programmeGantt(derived.programme)),
              caption: 'Indicative programme of works',
            });
          }
          context.estimate = derived.estimate;
          context.figures = figures;
          builder = await docx.costingReport(context);

        } else if (kind === 'supervision') {
          var items = C.loadChecklists();
          context.items = items;
          context.responses = store.get('supervision.responses') || {};
          context.evaluation = C.evaluateChecklist(items, context.responses);
          context.fieldChecks = (extra && extra.fieldChecks) || [];
          context.notes = store.get('supervision.notes') || [];
          context.boreholeRef = (derived.log && derived.log.borehole_ref) ||
            (derived.test && derived.test.borehole_ref) || '';
          builder = await docx.supervisionReport(context);

        } else if (kind === 'handover') {
          if (derived.design) {
            figures.push({
              image: await charts.toPng(charts.boreholeDesign(derived.design, derived.log)),
              caption: 'As-built borehole design', widthCm: 11,
            });
          }
          GWT.imageSlot.collect(store.get('photos.handover'), 'handover')
            .forEach(function (photo) {
              figures.push({ image: photo, caption: photo.caption, widthCm: 11 });
            });
          context.log = derived.log || {};
          context.design = derived.design;
          context.analysis = derived.analysis;
          context.assessment = derived.assessment;
          context.committee = store.get('handover.committee') || [];
          context.handoverDate = store.get('handover.date') || '';
          context.figures = figures;
          builder = await docx.handoverReport(context);
        }

        var filename = S.slug(siteLabel()) + '_' + kind + '_report.docx';
        await builder.save(filename);
        S.toast('Saved ' + filename, 'ok');
      });
    } catch (e) {
      S.toast('Could not build the report: ' + e.message, 'error');
      console.error(e);
    }
  }

  /* ------------------------------------------------------------------ render */

  function render() {
    var host = $('#page-host');
    S.clear(host);
    var page = PAGES[store.get('nav')] || PAGES.overview;
    try {
      S.append(host, page());
    } catch (e) {
      console.error(e);
      S.append(host, el('div.callout.callout-bad', [
        el('p', el('strong', 'Something went wrong drawing this page.')),
        el('p', e.message),
        el('p', button('Back to the overview', function () { goto('overview'); })),
      ]));
    }
    renderNav();
  }

  /* ----------------------------------------------------------- offline / PWA */

  /* Whether the browser has been asked to keep the app on disk. The toolkit is
   * used where the network is a luxury, so this is not a nicety: once the
   * worker is installed the app opens on a drilling site with no signal at
   * all. Registration is best-effort - file:// pages, private windows and
   * browsers without service worker support all fall through silently, and
   * the app works exactly as before in every one of them. */
  function registerServiceWorker() {
    if (!('serviceWorker' in navigator)) return;
    if (location.protocol !== 'https:' && location.hostname !== 'localhost'
      && location.hostname !== '127.0.0.1') return;
    navigator.serviceWorker.register('sw.js').then(function (reg) {
      /* Once it controls the page the app is on disk; say so where the user
       * is deciding whether to trust it in the field. */
      navigator.serviceWorker.ready.then(refreshInstallCard);
      reg.addEventListener('updatefound', function () {
        var incoming = reg.installing;
        if (!incoming) return;
        incoming.addEventListener('statechange', function () {
          /* "installed" with a controller already present means this is an
           * update, not a first install - say so rather than reloading, which
           * would throw away anything typed and not yet recomputed. */
          if (incoming.state === 'installed' && navigator.serviceWorker.controller) {
            S.toast('A newer version has been downloaded. It will be used the ' +
              'next time you open the app.', 'ok', 9000);
          }
        });
      });
    }).catch(function (e) {
      console.warn('Offline support unavailable:', e && e.message);
    });
  }

  /* Chromium hands over its install prompt exactly once and only if the page
   * refuses the default one, so it is stashed here and spent from the
   * Overview page's button. */
  var installPrompt = null;

  /* The card lives on the Overview page, and these events arrive whenever the
   * browser feels like it - including while a form is being filled in
   * elsewhere. Redraw only the page that shows the card, so nothing a user
   * has half-typed is thrown away to announce something they can see later. */
  function refreshInstallCard() {
    if (store.get('nav', 'overview') === 'overview') render();
  }

  function watchInstallPrompt() {
    global.addEventListener('beforeinstallprompt', function (event) {
      event.preventDefault();
      installPrompt = event;
      refreshInstallCard();
    });
    global.addEventListener('appinstalled', function () {
      installPrompt = null;
      S.toast('Installed. The toolkit now opens without a network.', 'ok');
      refreshInstallCard();
    });
  }

  function offlineReady() {
    return typeof navigator !== 'undefined' && 'serviceWorker' in navigator
      && !!navigator.serviceWorker.controller;
  }

  function installCard() {
    var ready = offlineReady();
    if (!installPrompt && !ready) return null;
    return card('Field use without a network', [
      ready ? el('div.callout.callout-ok', [
        el('p', el('strong', 'This app is saved on the device')),
        el('p', 'It will open and work with no network at all. Sample ' +
          'projects, the standards tables and every calculation are already ' +
          'here; only the live water point lookup needs a connection.'),
      ]) : null,
      installPrompt ? el('p', 'Install the toolkit on this device and it opens ' +
        'like any other application — full screen, no address bar. Everything ' +
        'still runs on the device; nothing is uploaded.') : null,
      installPrompt ? button('Install', function () {
        var prompt = installPrompt;
        installPrompt = null;
        prompt.prompt();
        prompt.userChoice.then(function (choice) {
          if (choice && choice.outcome !== 'accepted') refreshInstallCard();
        });
      }) : null,
    ].filter(Boolean));
  }

  /* -------------------------------------------------------------------- boot */

  async function init() {
    restoreApiKey();
    var strandedKey = '';
    if (store.restore()) {
      /* a mirrored session may predate a field being added */
      var merged = Object.assign(blankState(), store.state);
      /* An earlier build wrote the key into localStorage with the rest of the
       * session. Without this sweep it would be re-hydrated forever. */
      if (merged.extraction && merged.extraction.apiKey) {
        strandedKey = merged.extraction.apiKey;
        delete merged.extraction.apiKey;
      }
      store.replace(merged);
      if (strandedKey) store.persist();
    }
    applyTheme();
    renderChrome();
    render();
    if (strandedKey) {
      /* It sat unencrypted on disk, so removing it is not enough: it has to
       * be treated as disclosed and rotated. */
      S.toast('An API key was found in this browser\'s long-term storage and ' +
        'has been removed. Enter it again if you need it, and rotate it at ' +
        'console.anthropic.com — it was stored unencrypted.', 'warn', 20000);
    }
    registerServiceWorker();
    watchInstallPrompt();

    $('#nav-toggle').addEventListener('click', function () {
      $('#app-nav').classList.toggle('open');
    });

    if (Object.keys(store.get('sources') || {}).length) {
      await S.withBusy($('#page-host'), 'Restoring your session…', async function () {
        await recompute();
        await runInversions({ quiet: true });
      });
      render();
    }
  }

  GWT.app = {
    init: init, store: store, derived: derived, goto: goto, render: render,
    recompute: recompute, runInversions: runInversions, config: config,
    blankState: blankState, PAGES: PAGES, buildReport: buildReport,
    siteLatLon: siteLatLon, utmToLatLon: utmToLatLon,
    templates: TEMPLATE_SPECS, recomputeState: recomputeState,
    loadSample: loadSample, uploadZone: uploadZone,
    projectPayload: projectPayload, projectSummary: projectSummary,
    summaryFromProjectFile: summaryFromProjectFile,
    commitSpineScreens: commitSpineScreens, spineDecide: spineDecide,
    lookUpWaterPoints: lookUpWaterPoints, parseLatLon: parseLatLon,
    signOffFor: signOffFor, offlineReady: offlineReady,
    projectState: projectState, reportReadiness: reportReadiness,
    getApiKey: getApiKey, setApiKey: setApiKey, forgetApiKey: forgetApiKey,
    renderAutosaveBanner: renderAutosaveBanner,
  };

  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', init);
    } else {
      init();
    }
  }
}(typeof window !== 'undefined' ? window : globalThis));

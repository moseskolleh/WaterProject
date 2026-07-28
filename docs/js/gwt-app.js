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
      theme: 'auto',
    };
  }

  var store = S.createStore(blankState(), { persistKey: STORE_KEY });

  /* Derived results are recomputed rather than persisted: they are large,
   * they are cheap to rebuild, and a stale analysis beside fresh data is the
   * one thing a report must never contain. */
  var derived = {
    soundings: null, inversions: null, interpretations: null,
    log: null, test: null, analysis: null, sample: null, assessment: null,
    design: null, estimate: null, programme: null,
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
        var psheets = await S.readXlsx(S.base64ToBytes(sources.pumping.b64));
        derived.test = C.pumpingFromGrid(psheets[0].rows, sources.pumping.name);
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

  function projectPayload() {
    return {
      format: 'groundwater-toolkit-project',
      version: 1,
      saved: new Date().toISOString(),
      state: store.state,
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
            : 'Meets health based guidelines')
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
          uploadZone('pumping', 'Pumping test (.xlsx)',
            'Step or constant discharge with recovery'),
          uploadZone('quality', 'Water quality results (.xlsx)',
            'Parameter · value · unit from the laboratory'),
        ]),
        el('p.muted', { style: { marginTop: '0.8rem' } },
          'Not sure of the layout? The Templates page has a blank workbook for ' +
          'each of these.'),
      ]),

      nextStep('New to the toolkit? The guided start walks through one borehole ' +
        'from field sheet to signed report.', 'Guided start', 'guided'),
    ];
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

  PAGES.site = function () {
    var site = store.get('site');
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
          field('Elevation (m)', S.numberInput(site.elevation_m, bindNum('elevation_m'))),
          field('Date', S.textInput(site.date, bind('date'))),
        ]),
        latlon ? el('p.muted', 'Interpreted position: ' + latlon.lat.toFixed(5) +
          '°N, ' + latlon.lon.toFixed(5) + '°E' +
          (latlon.fromUtm ? ' (converted from UTM zone ' + latlon.zone + ')' : '') +
          (latlon.chiefdom ? ' — inside ' + latlon.chiefdom + ' chiefdom' : '')) : null,
      ]),

      mapNode ? card('Where the site sits', [
        charts.figure(mapNode, 'Project location within Sierra Leone',
          { filename: 'site_location' }),
        el('p.muted', C.POPULATION_CREDIT),
      ]) : null,

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
    var zone = site.utm_zone || (e > 500000 ? 28 : 29);
    var ll = utmToLatLon(e, n, zone);
    if (!ll) return null;
    ll.fromUtm = true; ll.zone = zone;
    ll.chiefdom = chiefdomAt(ll.lat, ll.lon);
    return ll;
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
  function utmToLatLon(easting, northing, zone) {
    var a = 6378137.0, f = 1 / 298.257223563;
    var e2 = f * (2 - f);
    var e1 = (1 - Math.sqrt(1 - e2)) / (1 + Math.sqrt(1 - e2));
    var x = easting - 500000.0, y = northing;
    var k0 = 0.9996;
    var m = y / k0;
    var mu = m / (a * (1 - e2 / 4 - 3 * e2 * e2 / 64 - 5 * e2 * e2 * e2 / 256));
    var phi1 = mu + (3 * e1 / 2 - 27 * Math.pow(e1, 3) / 32) * Math.sin(2 * mu) +
      (21 * e1 * e1 / 16 - 55 * Math.pow(e1, 4) / 32) * Math.sin(4 * mu) +
      (151 * Math.pow(e1, 3) / 96) * Math.sin(6 * mu);
    var ep2 = e2 / (1 - e2);
    var c1 = ep2 * Math.pow(Math.cos(phi1), 2);
    var t1 = Math.pow(Math.tan(phi1), 2);
    var n1 = a / Math.sqrt(1 - e2 * Math.pow(Math.sin(phi1), 2));
    var r1 = a * (1 - e2) / Math.pow(1 - e2 * Math.pow(Math.sin(phi1), 2), 1.5);
    var d = x / (n1 * k0);
    var lat = phi1 - (n1 * Math.tan(phi1) / r1) *
      (d * d / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1 * c1 - 9 * ep2) * Math.pow(d, 4) / 24 +
       (61 + 90 * t1 + 298 * c1 + 45 * t1 * t1 - 252 * ep2 - 3 * c1 * c1) * Math.pow(d, 6) / 720);
    var lon = (d - (1 + 2 * t1 + c1) * Math.pow(d, 3) / 6 +
      (5 - 2 * c1 + 28 * t1 - 3 * c1 * c1 + 8 * ep2 + 24 * t1 * t1) * Math.pow(d, 5) / 120) /
      Math.cos(phi1);
    var lon0 = (zone - 1) * 6 - 180 + 3;
    var out = { lat: lat * 180 / Math.PI, lon: lon0 + lon * 180 / Math.PI };
    return isFinite(out.lat) && isFinite(out.lon) ? out : null;
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

  /* --- pumping test --------------------------------------------------------- */

  PAGES.pumping = function () {
    var nodes = [
      pageHead('Pumping test', 'Cooper-Jacob, Theis and recovery on the same ' +
        'readings, a step drawdown analysis where the test has steps, and a safe ' +
        'yield reported as a range over the assumptions it rests on.'),
      card('Test data', [
        uploadZone('pumping', 'Pumping test sheet (.xlsx)',
          'Step or constant discharge, with the recovery block'),
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

    nodes.push(reportCard('Pumping test report', 'pumping',
      'Test details, the full field data tables, each analysis method with its ' +
      'figure, the results summary and the yield recommendation.'));
    nodes.push(nextStep('Next, assess the water quality.', 'Water quality', 'quality'));
    return nodes;
  };

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
      exceeds_health: 'row-bad', exceeds_national: 'row-warn',
      exceeds_aesthetic: 'row-warn', within_limits: '',
    };

    nodes.push(card('Verdict', [
      el('div.callout' + (a.health_exceedances.length ? '.callout-bad'
        : (a.aesthetic_exceedances.length ? '.callout-warn' : '.callout-ok')),
        el('p', a.verdict)),
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
            var tone = v === 'exceeds_health' ? 'bad'
              : (v === 'within_limits' ? 'ok'
                : (v.indexOf('exceeds') === 0 ? 'warn' : null));
            return S.badge(docx.statusLabel(v), tone);
          } },
        { key: 'remark', label: 'Remark' },
      ], a.rows, { rowClass: function (row) { return toneFor[row.status] || ''; } }),
    ]));

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

  /* --- water points --------------------------------------------------------- */

  PAGES.waterpoints = function () {
    var latlon = siteLatLon();
    var points = derived.waterPoints || [];
    var nodes = [
      pageHead('Water points', 'Before drilling a new borehole, check what is ' +
        'already there. A broken improved source nearby is usually cheaper to ' +
        'rehabilitate; a working one inside the service radius may already serve ' +
        'the community.'),
      card('Water point inventory', [
        el('p.muted', 'Upload a Water Point Data Exchange (WPdx+) export for the ' +
          'district as CSV. The app never contacts a remote service on its own, ' +
          'so the data you analyse is the data you brought.'),
        el('div.btn-row', [
          button('Upload WPdx CSV', async function () {
            var file = await S.pickFile('.csv,text/csv');
            if (!file) return;
            try {
              var text = await S.readFile(file, 'text');
              derived.waterPoints = C.parseWpdxRecords(S.parseCsv(text));
              S.toast(derived.waterPoints.length + ' water points read.', 'ok');
              render();
            } catch (e) {
              S.toast('Could not read that CSV: ' + e.message, 'error');
            }
          }),
          points.length ? button('Clear', function () {
            derived.waterPoints = null; render();
          }, { variant: 'ghost' }) : null,
        ]),
        points.length ? el('p.muted', points.length + ' water points loaded. ' +
          C.WPDX_CREDIT) : null,
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
      var decision = C.rehabVsDrill(points, latlon.lat, latlon.lon);
      var tone = decision.recommendation === C.DRILL_NEW ? '.callout-ok'
        : (decision.recommendation === C.ASSESS_REHAB ? '.callout-warn' : '.callout');
      nodes.push(card('Rehabilitate or drill?', [
        el('div.callout' + tone, [
          el('p', el('strong', decision.headline)),
          el('p', decision.rationale),
        ]),
        decision.nearby.length ? S.table([
          { key: 'distance_m', label: 'Distance (m)', align: 'right',
            format: function (v) { return Math.round(v); } },
          { key: 'source', label: 'Source' },
          { key: 'status_text', label: 'Status' },
          { key: 'functional', label: 'Functional',
            format: function (v) {
              return S.badge(v === true ? 'yes' : (v === false ? 'no' : 'unknown'),
                v === true ? 'ok' : (v === false ? 'bad' : null));
            } },
          { key: 'improved', label: 'Improved',
            format: function (v) { return v ? 'yes' : 'no'; } },
        ], decision.nearby.slice(0, 30)) : null,
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
    } else {
      nodes.push(S.empty('Enter the site GPS position on the Site page to get a ' +
        'rehabilitate-or-drill recommendation.',
        button('Site & maps', function () { goto('site'); }, { variant: 'ghost' })));
    }
    return nodes;
  };

  /* --- coverage gap --------------------------------------------------------- */

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
        el('p.muted', points.length
          ? points.length + ' water points loaded from the Water points page.'
          : 'Load a WPdx export on the Water points page to compute coverage.'),
        !points.length ? button('Water points', function () { goto('waterpoints'); }) : null,
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
        el('p', ['The full server version of the toolkit runs on Streamlit and ' +
          'adds AI-assisted extraction from scanned field sheets. A WebAssembly ' +
          'build of that same app is also published here — it runs the real ' +
          'Python package in the browser, at the cost of a 60 MB first load.']),
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

  /* Build and download a report, rasterising the on-screen figures so the
   * document carries exactly the figures the page shows. */
  function reportCard(title, kind, description, extra) {
    return card(title, [
      el('p.muted', description),
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
        var context = { style: cfg.style, site: store.get('site') };
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

  /* -------------------------------------------------------------------- boot */

  async function init() {
    if (store.restore()) {
      /* a mirrored session may predate a field being added */
      var merged = Object.assign(blankState(), store.state);
      store.replace(merged);
    }
    applyTheme();
    renderChrome();
    render();

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
  };

  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', init);
    } else {
      init();
    }
  }
}(typeof window !== 'undefined' ? window : globalThis));

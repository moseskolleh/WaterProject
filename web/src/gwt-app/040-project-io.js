
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
    /* the asset record goes out with the rising main the design now
     * specifies, as the registry page shows it (PLAN.md step 7.3) */
    if (state.asset) {
      var record = C.assetFromDict(state.asset);
      if (record) {
        state.asset = C.assetWithRisingMain(record, derived.design ? derived.design.rising_main
          : null);
      }
    }
    /* the ledger goes at the top of the file, where the Python app writes
     * and reads it, and not twice, with the borehole's outcome as the
     * project now holds it: a corrected log corrects it */
    var ledger = currentLedger();
    delete state.ledger;
    /* the issue records likewise (PLAN.md step 8.1) */
    var issued = C.cleanIssueRecords(state.issued);
    delete state.issued;
    /* the calibration set in force belongs to this browser, not the project,
     * and so do the reports waiting on it */
    delete state.calibration;
    delete state.reports;
    /** @type {Record<string, *>} */
    var payload = {
      format: 'groundwater-toolkit-project',
      schema: C.PROJECT_SCHEMA,
      saved: new Date().toISOString(),
      summary: projectSummary(),
      ledger: ledger,
      issued: issued,
    };
    /* what the project records of its contractor's work, for the Portfolio
     * page's contractor scorecards (PLAN.md step 6.3), at the top of the
     * file where the Python app writes and reads it too; only where there
     * is something in it, as a key an older toolkit ignores */
    var works = currentWorks();
    if (works) payload.works = works;
    payload.state = state;
    return payload;
  }

  function saveProject() {
    var name = S.slug(siteLabel()) + '.gwt.json';
    S.download(name, JSON.stringify(projectPayload(), null, 1), 'application/json');
    S.toast('Project saved as ' + name, 'ok');
  }

  /* A project saved before the checklists carried stable ids keys its
   * answers by position. Carry them onto the questions they answered so a
   * row inserted in the CSV never moves anybody's ticks. */
  function migrateLoadedState(state) {
    var sup = state && state.supervision;
    if (sup && sup.responses && typeof sup.responses === 'object') {
      sup.responses = C.migrateChecklistResponses(sup.responses);
    }
    return state;
  }

  /* A field test in progress lives in the session - the pumping test
   * co-pilot's under pumpCopilot, the VES co-pilot's under vesCopilot, the
   * drilling log co-pilot's under drillCopilot - and opening a project or a
   * sample must not be what ends it: readings taken at the well, the peg or
   * the rig cannot be taken again once the crew has packed up. The one on this device is carried into the project opened, even over
   * one the project file brings, since the file is still on disk and the
   * test here is not. Only "Reset everything" clears it.
   *
   * The calibration set in force (PLAN.md step 5.3) belongs to this browser
   * too, and stays in force for every project or sample opened. A project
   * file never brings one: a set is put in force only on the Portfolio
   * page, where a named person adopts it. So do the reports waiting on this
   * phone (PLAN.md step 7.1), which name boreholes of any project: a project
   * file neither carries nor brings them. */
  var FIELD_SESSIONS = ['pumpCopilot', 'vesCopilot', 'drillCopilot'];

  function keepBrowserState(next) {
    FIELD_SESSIONS.forEach(function (key) {
      if (store.state[key]) next[key] = store.state[key];
    });
    next.calibration = store.state.calibration || null;
    next.reports = store.state.reports || { queue: [], held: [] };
    return next;
  }

  async function openProject() {
    var file = await S.pickFile('.json,.gwt,application/json');
    if (!file) return;
    try {
      await loadProject(await S.readFile(file, 'text'));
    } catch (e) {
      S.toast('That file is not a Groundwater Toolkit project: ' + e.message, 'error');
    }
  }

  /* A project file's text, made the working session. The file's inversion
   * cache comes in with the rest of its state, so a survey saved after it
   * was inverted opens with its models and inverts nothing; a file saved
   * before the cache existed, or by the other app, inverts as it always
   * did. Resolves once any inversion it needed is in. */
  async function loadProject(text) {
    var payload = JSON.parse(text);
    var state = payload.state || payload;
    if (!state || typeof state !== 'object') throw new Error('not a project file');
    var schema = payload.state ? C.payloadSchema(payload) : 1;
    /* a file of a later schema says so instead of half-loading in silence */
    var newer = schema > C.PROJECT_SCHEMA;
    /* the ledger is at the file's top level; a bare state carries its own */
    state.ledger = C.cleanLedger(payload.state ? C.migratePayload(payload).ledger : state.ledger);
    /* and so are the issue records (PLAN.md step 8.1) */
    state.issued = C.cleanIssueRecords(payload.state ? C.migratePayload(payload).issued : state.issued);
    /* A hand-edited or old-build project file can carry a key; it must
     * never be adopted into this session's storage. The key held for this
     * tab is untouched - it belongs to this browser, not to the file. */
    if (state.extraction) delete state.extraction.apiKey;
    stopInversionsForNewProject();
    forgetTerrain();
    store.replace(keepBrowserState(migrateLoadedState(Object.assign(blankState(), state))));
    applyTheme();
    inversionsStopped = false;
    /* any inversion still needed is started in here, before the page is
     * drawn, so the page says it is running */
    await recompute();
    renderChrome();
    render();
    S.toast(newer ? 'Project loaded. This file was saved in project format ' + schema +
      '; this app reads format ' + C.PROJECT_SCHEMA + '. What it does not recognise is not ' +
      'restored.' : 'Project loaded.', newer ? 'warn' : 'ok');
    await inversionsSettled();
  }

  async function loadSample(key) {
    var sample = (GWT.data.samples || {})[key];
    if (!sample) return;
    /* the workbooks themselves are a bundle of their own, fetched the first
     * time a sample is opened */
    try {
      if (!GWT.hasBundle('samples')) await GWT.load('samples');
    } catch (e) {
      S.toast('Could not open the sample: ' + e.message, 'error');
      return;
    }
    var fresh = blankState();
    fresh.nav = store.get('nav');
    fresh.theme = store.get('theme', 'auto');
    Object.keys(sample.site || {}).forEach(function (k) {
      fresh.site[k] = sample.site[k];
    });
    /* Each source records the bundled file it came from. The certification
     * gate reads it, so every report this project produces says on its own
     * cover that it describes a worked example; it is saved with the project,
     * so reopening one does not quietly turn it into somebody's field work;
     * and an upload replaces the whole source object, so dropping real data
     * on a role clears the marker for that role and nothing else. */
    fresh.sources = {};
    Object.keys(sample.files).forEach(function (role) {
      fresh.sources[role] = {
        name: sample.files[role].name, b64: sample.files[role].b64,
        sample: sample.files[role].path || sample.files[role].name,
      };
    });
    stopInversionsForNewProject();
    forgetTerrain();
    store.replace(keepBrowserState(fresh));
    inversionsStopped = false;
    await recompute();
    renderChrome();
    render();
    S.toast('Loaded ' + sample.label + '.', 'ok');
    await inversionsSettled();
  }

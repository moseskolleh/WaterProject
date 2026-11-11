
  /* -------------------------------------------------------------------- boot */

  /* The saved session, made the working one. Resolves to where it came
   * from (see store.restore) and whether it carried an API key. */
  async function adoptSaved() {
    var from = await store.restore();
    var strandedKey = '';
    if (from) {
      /* a mirrored session may predate a field being added */
      var merged = Object.assign(blankState(), store.state);
      /* An earlier build wrote the key into localStorage with the rest of the
       * session. Without this sweep it would be re-hydrated forever. */
      if (merged.extraction && merged.extraction.apiKey) {
        strandedKey = merged.extraction.apiKey;
        delete merged.extraction.apiKey;
      }
      store.replace(migrateLoadedState(merged));
    }
    return { from: from, strandedKey: strandedKey };
  }

  /* This tab takes the saving over from another one, and opens what that
   * one saved: what it holds itself is at best what the other tab had when
   * this one opened. */
  async function continueHere() {
    try {
      await storage.takeOver();
    } catch (e) {
      S.toast('This tab could not take the saving over: ' + e.message, 'error');
      return;
    }
    stopInversionsForNewProject();
    forgetTerrain();
    var adopted = await adoptSaved();
    if (!adopted.from) store.replace(blankState());
    inversionsStopped = false;
    await store.persist();
    applyTheme();
    await recompute();
    renderChrome();
    render();
    await inversionsSettled();
  }

  async function init() {
    restoreApiKey();
    var adopted = await adoptSaved();
    var strandedKey = adopted.strandedKey;
    if (adopted.from === 'localStorage') {
      /* An earlier build's session, moved into IndexedDB here. The old key
       * goes only once the new copy has been read back as this session; a
       * move that fails leaves it where it was, and the banner says the
       * copy is no longer being updated. */
      if (await store.persist()) await storage.retireLegacy(store.state);
    } else {
      /* Nothing changed, so nothing much is written - but a browser that
       * will not store anything, or a tab that is not the one saving, is
       * found out now, before anything is typed into it. */
      store.persist();
    }
    /* An address that names a page wins over the page the session was left
     * on: it is what the user followed to get here. */
    var start = routeFrom(global.location.hash);
    if (start.key) {
      store.set('nav', start.key);
      route.item = start.item;
      route.focused = !start.item;
    }
    applyTheme();
    renderChrome();
    render();
    /* the first step of the history names its page too, so back returns to
     * it; replaced, since it is the same step */
    if (!start.key || start.unknown) {
      var shown = store.get('nav');
      global.location.replace(hashFor(
        Object.prototype.hasOwnProperty.call(PAGES, shown) ? shown : 'overview', route.item));
    }
    global.addEventListener('hashchange', followAddress);
    /* The last change before the tab is put away or closed is written now
     * rather than after the autosave's 400 ms, which the page may not live
     * to see: a phone freezes a hidden tab, and may then discard it. Hidden
     * is the dependable moment, since the page still runs to finish the
     * write; on pagehide it is a best effort, as IndexedDB, unlike
     * localStorage, does not write synchronously. */
    global.addEventListener('pagehide', function () { store.flush(); });
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'hidden') store.flush();
    });
    if (strandedKey) {
      /* It sat unencrypted on disk, so removing it is not enough: it has to
       * be treated as disclosed and rotated. */
      S.toast('An API key was found in this browser\'s long-term storage and ' +
        'has been removed. Enter it again if you need it, and rotate it at ' +
        'console.anthropic.com — it was stored unencrypted.', 'warn', 20000);
    }
    registerServiceWorker();
    watchInstallPrompt();

    watchNavToggle();

    if (Object.keys(store.get('sources') || {}).length) {
      /* the mirrored session carries its inversion cache, so a reload
       * inverts nothing that was inverted before it */
      await S.withBusy($('#page-host'), 'Restoring your session…', recompute);
      render();
      await inversionsSettled();
    }
  }

  GWT.app = {
    init: init, store: store, derived: derived, goto: goto, render: render,
    recompute: recompute, runInversions: runInversions, config: config,
    inversionsSettled: inversionsSettled, loadProject: loadProject,
    reanalyseTest: reanalyseTest, cancelWork: cancelWork, working: working,
    blankState: blankState, PAGES: PAGES, buildReport: buildReport, buildDeskStudy: buildDeskStudy,
    buildCalibration: buildCalibration, buildScorecards: buildScorecards, currentWorks: currentWorks,
    siteLatLon: siteLatLon, utmToLatLon: utmToLatLon,
    templates: TEMPLATE_SPECS, recomputeState: recomputeState,
    loadSample: loadSample, uploadZone: uploadZone,
    projectPayload: projectPayload, projectSummary: projectSummary,
    summaryFromProjectFile: summaryFromProjectFile,
    commitSpineScreens: commitSpineScreens, spineDecide: spineDecide,
    lookUpWaterPoints: lookUpWaterPoints, parseLatLon: parseLatLon,
    waterPointsSearchRadius: waterPointsSearchRadius, waterPointsSearched: waterPointsSearched,
    signOffFor: signOffFor, offlineReady: offlineReady,
    projectState: projectState, reportReadiness: reportReadiness,
    getApiKey: getApiKey, setApiKey: setApiKey, forgetApiKey: forgetApiKey,
    renderAutosaveBanner: renderAutosaveBanner,
    storage: storage, continueHere: continueHere,
    hashFor: hashFor, routeFrom: routeFrom,
    sampleRanges: sampleRanges, rangeFor: rangeFor, surveyOdds: surveyOdds,
    costSpreads: costSpreads, surveyMeasurements: surveyMeasurements,
    /* documents issued and verified (PLAN.md step 8.1) */
    issueFor: issueFor, recordIssue: recordIssue, verifySession: verifySession,
    /* the evidence bundle (PLAN.md step 8.3) */
    bundleSession: bundleSession, bundleDocuments: bundleDocuments, evidenceBundle: evidenceBundle,
    /* the Topography and terrain card's files, read and analysis */
    terrainSession: function () { return terrainSession; },
  };

  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', init);
    } else {
      init();
    }
  }
}(typeof window !== 'undefined' ? window : globalThis));

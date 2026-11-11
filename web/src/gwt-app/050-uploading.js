
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
        if (role === 'ves') inversionsStopped = false;
        await S.withBusy($('#page-host'), 'Reading ' + file.name + '…', recompute);
        render();
        S.toast(file.name + ' loaded.', 'ok');
        await inversionsSettled();
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

  /* The VES inversion is the one expensive computation. It runs in the engine
   * worker a sounding at a time, with its progress in the work bar and a
   * button there to stop it, and the page stays live meanwhile.
   *
   * A newer run replaces an older one. A recompute replaces a run only when
   * the soundings it reads are not the ones the run is inverting; when they
   * are - a discharge typed on the Pumping test page while the survey is
   * still inverting - the run carries on and commits onto the new reading of
   * them. Only the latest run commits, and only onto its own soundings: an
   * older run's results are dropped rather than written over the newer
   * run's, and a stopped run leaves what was there before it.
   *
   * Every sounding's inversion, or the message it failed with, is kept in
   * the store's inversionCache as soon as it is in, under the SHA-256 of the
   * sounding's readings, the VES settings and the engine
   * (C.inversionCacheKey). The cache is saved with the project and mirrored
   * with the session. A recompute, and a run asked to reuse it, take a
   * sounding from it rather than inverting it again; Re-run inversion runs
   * every sounding, as it says. An entry that is not sound is not used
   * (C.inversionFromCache), and the sounding is inverted as if there were
   * none. */
  var inversionRun = 0;
  /* the latest run: {run, keys, soundings, running, promise} */
  var inversionTask = null;
  /* Cancel was pressed on an inversion: a recompute does not start it again
   * on its own until something else asks for one */
  var inversionsStopped = false;

  function inversionKeys(soundings, cfg) {
    return soundings.map(function (sounding) { return C.inversionCacheKey(sounding, cfg); });
  }

  function sameKeys(a, b) {
    return !!a && !!b && a.length === b.length && a.every(function (key, i) {
      return key !== null && key === b[i];
    });
  }

  /* The cache's answer for one sounding: {result} or {error}, or null. */
  function cachedInversion(key, sounding, cfg) {
    if (!key) return null;
    var cache = store.get('inversionCache') || {};
    return Object.prototype.hasOwnProperty.call(cache, key)
      ? C.inversionFromCache(cache[key], key, sounding, cfg) : null;
  }

  function rememberInversion(key, sounding, result, error) {
    var entry = C.inversionCacheEntry(key, sounding, result, error);
    if (!entry) return;
    var cache = Object.assign({}, store.get('inversionCache') || {});
    cache[key] = entry;
    store.set('inversionCache', cache);
  }

  /* Only the current soundings' entries are kept, so the cache and the file
   * it is saved in stay the size of the survey. */
  function pruneInversionCache(keys) {
    var cache = store.get('inversionCache') || {}, kept = {};
    keys.forEach(function (key) {
      if (key && Object.prototype.hasOwnProperty.call(cache, key)) kept[key] = cache[key];
    });
    if (Object.keys(kept).length !== Object.keys(cache).length) store.set('inversionCache', kept);
  }

  /* Put one run's outcomes, one per sounding, on show. */
  function commitInversions(soundings, outcomes, cfg) {
    var results = [], interpretations = [];
    soundings.forEach(function (sounding, i) {
      var outcome = outcomes[i];
      if (!outcome || !outcome.result) return;
      results.push(outcome.result);
      /* read by the edges the calibration set in force fitted for the
       * geology unit under the sounding, if any */
      interpretations.push(C.interpretModel(sounding, outcome.result.model,
        C.configForSounding(cfg, sounding)));
    });
    derived.inversions = results;
    derived.interpretations = interpretations;
    C.rankInterpretations(interpretations, store.get('ves.preferredOrder'), cfg.ves);
  }

  /* After a recompute has read the soundings: put the cache's inversions of
   * them on show, and say what is left to do. Returns a function that starts
   * the run the soundings still need, or null when there is none to start -
   * every sounding was in the cache, the run already under way is for these
   * very soundings, or Cancel was pressed and nothing has asked since. */
  function adoptInversions(cfg) {
    var soundings = derived.soundings;
    var task = inversionTask;
    var keys = soundings && soundings.length ? inversionKeys(soundings, cfg) : null;
    var carryOn = !!(keys && task && task.running && task.run === inversionRun &&
      sameKeys(task.keys, keys));
    if (carryOn) {
      task.soundings = soundings;
    } else {
      inversionRun += 1;
      engine.cancel('invert');
    }
    derived.inversions = null;
    derived.interpretations = null;
    if (!keys) {
      inversionTask = null;
      return null;
    }
    var outcomes = soundings.map(function (sounding, i) {
      return cachedInversion(keys[i], sounding, cfg);
    });
    if (outcomes.every(Boolean)) {
      commitInversions(soundings, outcomes, cfg);
      return null;
    }
    if (carryOn || inversionsStopped) return null;
    return function () { return runInversions({ reuse: true }); };
  }

  /* Invert the current soundings. With options.reuse, a sounding the cache
   * holds is taken from it and only the others are inverted. Always
   * resolves, once the run has committed, been replaced or been stopped. */
  function runInversions(options) {
    var reuse = !!(options && options.reuse);
    var run = ++inversionRun;
    inversionsStopped = false;
    engine.cancel('invert');
    var soundings = derived.soundings;
    if (!soundings || !soundings.length) {
      inversionTask = null;
      derived.inversions = null; derived.interpretations = null;
      return Promise.resolve();
    }
    var cfg = config();
    var task = inversionTask = { run: run, keys: inversionKeys(soundings, cfg),
      soundings: soundings, running: true, promise: null };
    task.promise = invertSoundings(task, cfg, reuse).finally(function () {
      task.running = false;
    });
    return task.promise;
  }

  async function invertSoundings(task, cfg, reuse) {
    var run = task.run, soundings = task.soundings, keys = task.keys;
    var outcomes = soundings.map(function (sounding, i) {
      return reuse ? cachedInversion(keys[i], sounding, cfg) : null;
    });
    var todo = [];
    outcomes.forEach(function (outcome, i) { if (!outcome) todo.push(i); });
    var n = todo.length;
    if (n) {
      var job = workBegin('invert', 'Inverting ' + n + ' ' + S.plural(n, 'sounding'));
      try {
        for (var t = 0; t < n; t++) {
          var i = todo[t], sounding = soundings[i];
          var which = sounding.sounding_id + (n > 1 ? ' (' + (t + 1) + ' of ' + n + ')' : '');
          workProgress(job, t / n, which);
          try {
            var result = await engine.invert(sounding, cfg, {
              onProgress: function (fraction, layers) {
                workProgress(job, (t + fraction) / n, which + ', ' + layers);
              },
            });
            if (run !== inversionRun) return;
            outcomes[i] = { result: result };
            rememberInversion(keys[i], sounding, result, null);
          } catch (e) {
            if (engine.isCancelled(e) || run !== inversionRun) return;
            outcomes[i] = { error: e.message };
            rememberInversion(keys[i], sounding, null, e.message);
            S.toast(sounding.sounding_id + ': ' + e.message, 'warn');
          }
        }
      } finally {
        workEnd(job);
      }
    }
    /* a recompute that read these same soundings again has handed the run
     * its reading of them; any other has replaced the run. One still reading
     * the sources has not yet said which: it may be about to show other
     * soundings, or another setting, so the run commits nothing and leaves
     * the recompute to take these results from the cache (adoptInversions). */
    if (run !== inversionRun || recomputeState.running ||
        derived.soundings !== task.soundings) return;
    commitInversions(task.soundings, outcomes, cfg);
    pruneInversionCache(keys);
    rebuildDesign();
    rebuildCosting();
  }

  /* Another project is about to replace the store. A run for the outgoing
   * one is stopped here rather than when the incoming one's soundings have
   * been read: until then it would still be the latest run, and whatever it
   * finished would be written into the incoming project's cache. */
  function stopInversionsForNewProject() {
    inversionRun += 1;
    engine.cancel('invert');
  }

  /* The inversion the page is waiting for, if any: resolves once it is done. */
  function inversionsSettled() {
    return inversionTask && inversionTask.running ? inversionTask.promise : Promise.resolve();
  }

  /* The VES page's buttons: start the run, draw the page as it now stands
   * (running), and draw it again with the models once they are in. Re-run
   * inversion runs every sounding again; Invert now, offered after a run was
   * stopped, takes what that run finished from the cache. */
  function invertAndShow(reuse) {
    var inverted = runInversions({ reuse: reuse });
    render();
    inverted.then(refresh);
  }

  /* The range of models (PLAN.md step 3.1), asked for with a button: a few
   * seconds a sounding in the engine worker, with its progress in the work
   * bar and Cancel there. A range belongs to the inversion it was sampled
   * around and the settings it was sampled with, so it is kept against the
   * inversion object itself and its settings beside it: a new inversion, or
   * a changed range setting, finds no range and the button is offered
   * again. It is not saved with the project. Unlike an inversion, a range
   * cannot be checked on the way back in by recomputing a misfit, so a
   * saved one would have to be taken on trust; it is sampled again instead. */
  var ranges = new WeakMap();
  var rangeRun = 0;

  function rangeFor(inversion) {
    var kept = inversion ? ranges.get(inversion) : null;
    if (!kept) return null;
    return JSON.stringify(kept.settings) === JSON.stringify(config().ves_range)
      ? kept.range : null;
  }

  async function sampleRanges() {
    var run = ++rangeRun;
    engine.cancel('sampleRange');
    var inversions = derived.inversions || [];
    var interpretations = derived.interpretations || [];
    var soundings = derived.soundings || [];
    var cfg = config();
    var n = inversions.length;
    if (!n) return;
    var job = workBegin('range', 'Sampling the range of models for ' + n + ' ' +
      S.plural(n, 'sounding'));
    render();
    try {
      for (var t = 0; t < n; t++) {
        /* A recompute while this runs replaces the inversions (or clears
         * them while it inverts afresh): the rest would be sampled around
         * inversions no longer on show, and the live lists are no longer
         * the ones these indices count through. */
        if (derived.inversions !== inversions) return;
        var inversion = inversions[t];
        var id = interpretations[t].sounding_id;
        var sounding = soundings.filter(function (s) { return s.sounding_id === id; })[0];
        if (!sounding) continue;
        var which = id + (n > 1 ? ' (' + (t + 1) + ' of ' + n + ')' : '');
        workProgress(job, t / n, which);
        try {
          /* the models read by the edges the sounding itself is read by */
          var range = await engine.sampleRange(sounding, inversion, C.configForSounding(cfg, sounding), {
            onProgress: function (fraction, label) {
              workProgress(job, (t + fraction) / n, which + ', ' + label);
            },
          });
          if (run !== rangeRun) return;
          ranges.set(inversion, { range: range, settings: cfg.ves_range });
        } catch (e) {
          if (engine.isCancelled(e) || run !== rangeRun) return;
          S.toast(id + ': ' + e.message, 'warn');
        }
      }
    } finally {
      /* what was sampled before a stop is shown too */
      workEnd(job);
      refresh();
    }
  }

  /* The chance of a working borehole at every point (PLAN.md step 3.3), with
   * the range sampled around each inversion where there is one, placed as
   * the report places it: the point's own position, else the site's. The
   * map layers it reads are loaded with every working page and report. */
  function surveyOdds() {
    var site = store.get('site') || {};
    return C.surveyOdds(derived.interpretations || [],
      (derived.inversions || []).map(rangeFor), Number(site.utm_zone) || null,
      C.sitePosition(site), config());
  }

  /* The survey's first-ranked point as the costing reads it: its odds and
   * its sampled range (null where none). By position, not id: two points can
   * share an id. */
  function firstPointSurvey() {
    if (!(derived.interpretations || []).length) return { odds: null, range: null };
    var first = C.assessSiting(derived.interpretations, config().ves)[0].index;
    return { odds: surveyOdds()[first] || null,
      range: rangeFor((derived.inversions || [])[first]) };
  }

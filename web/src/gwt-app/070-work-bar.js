
  /* ------------------------------------------------------------- work bar */

  /* The engine work the page is waiting for, drawn above the page: what is
   * running, how far it has got, and a button to stop it. The page stays live
   * underneath - the work is in a worker - so the bar covers nothing, and it
   * stays in view as the page scrolls. A job shows only once it has run for
   * WORK_BAR_DELAY_MS, so a quick one never flashes it. Where the page does
   * its own computing there is no delay: the bar has to be on screen before
   * the page stops drawing, or there is no Cancel to press between one
   * sounding and the next. */
  var WORK_BAR_DELAY_MS = 150;
  var work = {};
  var workIds = 0;
  var workBarFrame = null;

  function workBegin(key, label) {
    var job = { id: String(++workIds), key: key, label: label, detail: '',
      fraction: 0, since: Date.now(),
      delay: engine.mode() === 'page' ? 0 : WORK_BAR_DELAY_MS };
    work[key] = job;
    setTimeout(drawWorkBarSoon, job.delay);
    return job;
  }

  function workProgress(job, fraction, detail) {
    if (work[job.key] !== job) return;
    job.fraction = Math.max(0, Math.min(1, fraction || 0));
    if (detail) job.detail = detail;
    drawWorkBarSoon();
  }

  function workEnd(job) {
    if (work[job.key] === job) delete work[job.key];
    drawWorkBarSoon();
  }

  function working(key) {
    return !!work[key];
  }

  function drawWorkBarSoon() {
    if (workBarFrame !== null) return;
    workBarFrame = requestAnimationFrame(function () {
      workBarFrame = null;
      drawWorkBar();
    });
  }

  /* Drawn in place: a bar rebuilt on every progress report would take the
   * Cancel button out from under the pointer about to press it. */
  function drawWorkBar() {
    var host = $('#work-status');
    if (!host) return;
    var now = Date.now();
    var jobs = Object.keys(work).map(function (key) { return work[key]; })
      .filter(function (job) { return now - job.since >= job.delay; });
    var ids = jobs.map(function (job) { return job.id; });
    Array.from(host.children).forEach(function (bar) {
      if (ids.indexOf(bar.getAttribute('data-job')) < 0) host.removeChild(bar);
    });
    jobs.forEach(function (job) {
      var bar = host.querySelector('[data-job="' + job.id + '"]');
      if (!bar) {
        bar = el('div.work-bar', { 'data-job': job.id, 'data-work': job.key }, [
          el('span.spinner'),
          el('div.work-text', [
            el('span.work-label', job.label),
            /* the host announces a job once, as it starts; not every step */
            el('span.work-detail', { 'aria-live': 'off' }),
            el('div.progress-track', { role: 'progressbar', 'aria-label': job.label,
              'aria-valuemin': '0', 'aria-valuemax': '100' }, el('div.progress-fill')),
          ]),
          button('Cancel', function () { cancelWork(job.key); }, { variant: 'ghost',
            title: 'Stop this computation; nothing it has done so far is kept' }),
        ]);
        host.appendChild(bar);
      }
      var percent = Math.round(100 * job.fraction);
      bar.querySelector('.work-detail').textContent = job.detail;
      bar.querySelector('.progress-fill').style.width = percent + '%';
      bar.querySelector('.progress-track').setAttribute('aria-valuenow', String(percent));
    });
  }

  /* The Cancel button. The worker is stopped mid-iteration if need be; on a
   * page with no worker the press is read between soundings, since a task
   * running on the page has it to itself until it returns. */
  function cancelWork(key) {
    if (!work[key]) return;
    if (key === 'invert') {
      inversionRun += 1;
      inversionsStopped = true;
      engine.cancel('invert');
      S.toast('The inversion was stopped, and the results on the page are as ' +
        'they were. The Geophysics page can run it again.', 'warn');
    } else if (key === 'range') {
      rangeRun += 1;
      engine.cancel('sampleRange');
      S.toast('The range of models was stopped; the ranges already sampled are ' +
        'kept, and the Geophysics page can sample the rest.', 'warn');
    } else if (key === 'pumping') {
      engine.cancel('analysePumping');
      S.toast('The pumping analysis was stopped. The test is still loaded, and ' +
        'the Pumping test page can run the analysis again.', 'warn');
    } else if (key === 'terrain') {
      /* the run is dropped with whatever it had read, the worker stopped
       * and the bar taken away (dropTerrainRead), at once even while the
       * page is still reading the files. A read under way cannot be
       * stopped and the run ends only after it, so the card is drawn
       * again here then; in the worker the run ends at once, and draws it
       * as it ends */
      var reading = terrainSession.reading;
      dropTerrainRead(terrainSession);
      if (reading) refresh();
      S.toast('The terrain analysis was stopped, and nothing of it is kept. The tiles ' +
        'are still on the Topography and terrain card, which can analyse them again.', 'warn');
    }
  }

  /* Work in the worker finishes whenever it finishes, and meanwhile somebody
   * may have started typing into the page: a redraw now would throw away a
   * value typed and not yet committed. So the page is redrawn now if no
   * field on it has focus, and otherwise as soon as that field loses it. */
  /* The field a redraw is waiting on. It is remembered as the field rather
   * than as a flag: a field that a redraw took away without losing focus
   * first never blurs, and a flag would then hold back every later redraw. */
  var refreshWaitsOn = null;
  function refresh() {
    var host = $('#page-host');
    var active = document.activeElement;
    var typing = active && active !== host && host.contains(active) &&
      /^(INPUT|TEXTAREA|SELECT)$/.test(active.tagName);
    if (!typing) {
      refreshWaitsOn = null;
      render();
      return;
    }
    if (refreshWaitsOn === active) return;
    refreshWaitsOn = active;
    active.addEventListener('blur', function () {
      /* after the field's own change handler has had its turn */
      setTimeout(function () {
        if (refreshWaitsOn !== active) return;
        refreshWaitsOn = null;
        render();
      }, 0);
    }, { once: true });
  }

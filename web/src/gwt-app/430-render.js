
  /* ------------------------------------------------------------------ render */

  /* The pages drawn with the first screen's scripts alone. Every other page
   * draws figures, and reads the map layers for a map or for the chiefdom
   * and district under the site's position that it states, so VIEW_BUNDLES
   * are fetched before one of them is first drawn and not before: the
   * Overview a phone opens on has no use for 760 KB of boundaries. Two
   * pages draw with the document writer's own words, so they need that too:
   * procurement labels its certificate lines with them, and water quality
   * its status column, so the page and the report cannot word a result
   * differently. */
  var FIRST_SCREEN = { overview: true, guided: true, templates: true,
    extract: true, settings: true, about: true, verify: true };
  var DRAWS_WITH_DOCX = { procurement: true, quality: true };
  /* A page that is a module of its own, fetched with what it draws with: the
   * pumping and VES co-pilots each draw one figure and no map, and the
   * drilling log co-pilot draws none but takes a photograph an interval. */
  var MODULE_PAGES = {
    pumpcopilot: ['charts', 'pumpCopilot'],
    vescopilot: ['charts', 'vesCopilot'],
    drillcopilot: ['imageSlot', 'drillCopilot'],
    /* the page a plate's QR code opens on a phone (PLAN.md step 7.1): a
     * photograph slot and nothing else, so it draws without the maps */
    report: ['imageSlot'],
  };

  function bundlesFor(key) {
    if (MODULE_PAGES[key]) return MODULE_PAGES[key];
    if (FIRST_SCREEN[key]) return [];
    return DRAWS_WITH_DOCX[key] ? REPORT_BUNDLES : VIEW_BUNDLES;
  }

  function pageTitle(key) {
    var title = '';
    NAV_GROUPS.forEach(function (group) {
      group[1].forEach(function (page) { if (page[0] === key) title = page[1]; });
    });
    return title;
  }

  /* Draw the page the store names. The promise is that page drawn: at once,
   * or once the bundles it needs have arrived, with a line saying what it is
   * waiting for in the meantime. */
  function render() {
    var host = $('#page-host');
    var key = Object.prototype.hasOwnProperty.call(PAGES, store.get('nav'))
      ? store.get('nav') : 'overview';
    /* the co-pilot's preview fit is stopped once its page is left */
    if (key !== 'vescopilot' && GWT.vesCopilot) GWT.vesCopilot.leave();
    if (key !== 'drillcopilot' && GWT.drillCopilot) GWT.drillCopilot.leave();
    var wanted = bundlesFor(key);
    if (!hasBundles(wanted)) {
      S.clear(host);
      S.append(host, [
        pageHead(pageTitle(key)),
        S.empty('Loading the maps and figures for this page…'),
      ]);
      renderNav();
      return need(wanted)
        .then(function () {
          /* drawn only if it is still the page asked for */
          if (store.get('nav') === key) return render();
          return null;
        }, function (e) {
          if (store.get('nav') !== key) return;
          S.clear(host);
          S.append(host, [
            pageHead(pageTitle(key)),
            el('div.callout.callout-bad', [
              el('p', el('strong', 'This page could not be loaded.')),
              el('p', e.message),
              el('p', button('Try again', function () { render(); })),
            ]),
          ]);
        });
    }
    bindModules();
    S.clear(host);
    var page = PAGES[key];
    try {
      S.append(host, page());
      showItem(host);
    } catch (e) {
      console.error(e);
      S.append(host, el('div.callout.callout-bad', [
        el('p', el('strong', 'Something went wrong drawing this page.')),
        el('p', e.message),
        el('p', button('Back to the overview', function () { goto('overview'); })),
      ]));
    }
    renderNav();
    return Promise.resolve();
  }

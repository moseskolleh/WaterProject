
  /* --- the desk study (PLAN.md step 4.4) ------------------------------------
   * The eleventh document, put together before anyone goes to the site, from
   * what the app holds now: the site, the maps, the terrain analysis on show
   * and its plan, the water points the Water points page loaded and the
   * earlier projects the Portfolio page holds, as the Python app's Site maps
   * page builds it. */
  function deskStudyCard() {
    return card('Desk study', [
      el('p.muted', 'The eleventh document, put together before anyone goes to the site: the ' +
        'geology and aquifer class under it, the terrain, its lineament candidates and the ' +
        'survey plan from the terrain analysis above, the water points the Water points page ' +
        'holds, the earlier projects the Portfolio page holds within 5 km, and the odds of a ' +
        'working borehole from the ground alone. Every copy is stamped as a pre-field document.'),
      el('div.btn-row', [
        button('Build the desk study (.docx)', function (event) {
          buildDeskStudy(event.target);
        }),
      ]),
    ]);
  }

  /* The terrain figures the desk study names, drawn again for paper from
   * the analysis on show, without touching the card's own, which are drawn
   * in the page's colours: the relief, the lineament candidates, their rose
   * where there is one, and the plan where it lays a line. */
  async function deskStudyFigures(session) {
    var result = session && session.result, out = {};
    if (!result || !result.desk) return out;
    var opts = { parts: result.parts, summary: result.summary, captions: result.captions,
      site: result.site, figureCredit: session.read.figureCredit, cfg: result.cfg.terrain };
    var lineamentOpts = Object.assign({}, opts, {
      captions: Object.assign({}, result.captions, result.lineamentCaptions), lineaments: result.lineaments,
      axes: { lons: session.read.grid.lons, lats: session.read.grid.lats } });
    var draws = [{ key: 'relief', draw: function () { return charts.terrainRelief(result.display, opts); } },
      { key: 'lineaments', draw: function () { return charts.lineamentMap(result.display, lineamentOpts); } }];
    if (result.lineaments.lineaments.length) {
      draws.push({ key: 'rose', draw: function () { return charts.lineamentRose(result.lineaments, lineamentOpts); } });
    }
    if (result.planGpx) {
      draws.push({ key: 'plan', draw: function () {
        return charts.surveyPlanMap(result.display, Object.assign({}, lineamentOpts, {
          captions: Object.assign({}, lineamentOpts.captions, result.planCaptions), plan: result.plan }));
      } });
    }
    /* one at a time, so that no more than one figure's canvas is held */
    for (var i = 0; i < draws.length; i++) out[draws[i].key] = await charts.toPng(draws[i].draw());
    return out;
  }

  async function buildDeskStudy(node) {
    var host = node ? node.closest('.card') : $('#page-host');
    try {
      await need(REPORT_BUNDLES);
    } catch (e) {
      S.toast('Could not build the desk study: ' + e.message, 'error');
      return;
    }
    charts.usePrintPalette(true);
    try {
      await S.withBusy(host, 'Building the desk study…', async function () {
        var site = store.get('site') || {};
        var session = terrainSession;
        var content = C.deskStudyContent(site, site.community || site.chiefdom || site.district || '',
          siteLatLon(), {
            waterPoints: derived.waterPoints || null,
            searchRadiusM: waterPointsSearchRadius(),
            portfolio: derived.portfolio || null,
            terrain: session.result ? session.result.desk || null : null,
            config: config(),
          });
        var context = { style: config().style, content: content, areaNote: areaNote(),
          areaMaps: await areaFigures(true), figures: await deskStudyFigures(session),
          issue: issueFor('desk_study') };
        var builder = GWT.docx.deskStudyReport(context);
        /* saved first: the builder has no record until it has built the document */
        var deskBytes = await builder.save('Desk_Study.docx');
        recordIssue(builder.record, 'Desk_Study.docx', deskBytes);
        S.toast(savedWords('Desk_Study.docx', builder.record), 'ok');
      });
    } catch (e) {
      S.toast('Could not build the desk study: ' + e.message, 'error');
      console.error(e);
    } finally {
      charts.usePrintPalette(false);
    }
  }


  /* ----------------------------------------- the survey's own report figures */

  /* The point the whole report argues for: reporting/geophysical.py
   * _preferred, which is the lowest rank, then the highest score, then the
   * identifier. The study-area caption names it, and a caption naming a
   * different peg from the one the conclusions recommend is a rig sent to the
   * wrong place. */
  function preferredInterpretation(interpretations) {
    var best = null;
    (interpretations || []).forEach(function (interp) {
      if (best === null) { best = interp; return; }
      var rank = interp.rank || 99, bestRank = best.rank || 99;
      if (rank !== bestRank) {
        if (rank < bestRank) best = interp;
        return;
      }
      var score = Number(interp.score) || 0, bestScore = Number(best.score) || 0;
      if (score !== bestScore) {
        if (score > bestScore) best = interp;
        return;
      }
      if (String(interp.sounding_id) < String(best.sounding_id)) best = interp;
    });
    return best;
  }

  /* The largest distance between any two positioned soundings, in km:
   * reporting/geophysical.py _survey_spread_km. Pegs kilometres apart are not
   * one site, and the caption says so rather than leaving a reader to measure
   * it off the scale bar. */
  function surveySpreadKm(interpretations) {
    var points = [], a, b, widest = 0;
    (interpretations || []).forEach(function (interp) {
      var pos = soundingLatLon(interp);
      if (pos) points.push(pos);
    });
    for (a = 0; a < points.length; a += 1) {
      for (b = a + 1; b < points.length; b += 1) {
        widest = Math.max(widest, C.geodesicDistanceM(
          points[a].lat, points[a].lon, points[b].lat, points[b].lon));
      }
    }
    return widest / 1000.0;
  }

  /* The study-area map that opens the Python geophysical report, with the
   * caption reporting/geophysical.py gives it. The browser drew this map for
   * the Site page but no report carried it, so the browser's geophysical
   * report opened on a district locator and never showed the reader the
   * ground the survey actually covered, or which peg the star is on. */
  async function studyAreaFigure(interpretations) {
    var node = studyAreaNode({ surveyOnly: true });
    if (!node) return null;
    var site = store.get('site') || {};
    var preferred = preferredInterpretation(interpretations);
    /* worded from what the map actually carries: the soundings with a
     * position, the star only where the ranking gives one and the point has
     * a position to draw it at */
    var marked = (interpretations || []).filter(function (interp) {
      return !!soundingLatLon(interp);
    }).map(function (interp) { return interp.sounding_id; });
    var ves = config().ves;
    var leaders = C.assessSiting(interpretations || [], ves).slice(0, 2)
      .map(function (r) { return r.sounding_id; });
    var caption = C.studyAreaCaption(site.community || 'the project area', marked,
      preferred ? preferred.sounding_id : '', leaders, surveyTie(interpretations));
    var spread = surveySpreadKm(interpretations);
    if (spread > 5.0) {
      caption += ' The survey points are up to ' + C.pyFixed(spread, 1) +
        ' km apart, which is unusually far for one site; the positions should ' +
        'be checked against the field notes.';
    }
    caption += ' Boundaries from geoBoundaries (CC BY 4.0).';
    return { image: await charts.toPng(node), caption: caption, widthCm: 14 };
  }

  /* The captions of the four subsurface maps and the pseudo-section are the
   * engine's, written from what each figure shows (C.subsurfaceCaption,
   * C.pseudosectionCaption), as reporting/geophysical.py writes them. This
   * one is fixed in both engines. */
  var GEOELECTRIC_SECTION_CAPTION = 'Interpreted geoelectric section along the ' +
    'traverse, with the soundings at their surveyed spacing rather than evenly ' +
    'spaced and drawn to the depth of investigation. Colour is layer ' +
    'resistivity; the dashed lines correlate boundaries between neighbouring ' +
    'soundings within reach of each other and are an interpretation, not a ' +
    'measured contact.';

  /* A figure the chart layer returned nothing for, with no reason from the
   * engine, is a defect in the drawing rather than a refusal the survey
   * earned. It is still named in the "not drawn" list, because a figure that
   * disappears without a word reads as one nobody attempted. */
  function figureRefusal(reason) {
    return reason || 'the figure could not be drawn from these data';
  }

  /* The maps and sections built from this survey's own soundings, mirroring
   * reporting/geophysical.py _add_subsurface_figures: the four subsurface
   * maps, the geoelectric section and the apparent-resistivity
   * pseudo-section, in that order, each attempted on its own so that none of
   * them costs the report the others - a survey whose curves never reached
   * basement has no depth-to-bedrock map but still has an aquifer thickness
   * map. What could not be drawn is carried back with it: the reason is
   * usually a GPS position nobody recorded, which a reviewer can ask for,
   * and a figure missing without a word reads as "the survey did not attempt
   * this". Returns null where the Python writes no section at all: with
   * fewer than two positioned soundings there is nothing to say about the
   * ground between them. `profileRefusal` is why the ground profile of
   * section 3 was not drawn, listed first as the Python lists it.
   *
   * Every interpretation goes to the maps and the section, positioned or
   * not: the engine places them in one zone, and a refusal can then say
   * which soundings lack a position and which lack the value. */
  async function subsurfaceFigures(interpretations, soundings, profileRefusal) {
    if (!C.subsurfaceFiguresApply(interpretations)) return null;
    var all = interpretations || [];
    var site = store.get('site') || {};
    var zone = site.utm_zone || C.surveyZone(all) || 28;
    var made = [], notDrawn = [], i, svg, anySurface = false;
    if (profileRefusal) notDrawn.push('ground profile: ' + profileRefusal);

    var maps = charts.subsurfaceMaps(all, { zone: zone });
    for (i = 0; i < maps.length; i += 1) {
      if (maps[i].reason || !maps[i].svg) {
        notDrawn.push(maps[i].name + ': ' + figureRefusal(maps[i].reason));
      } else {
        anySurface = anySurface || !!maps[i].data.surface_said;
        made.push({
          image: await charts.toPng(maps[i].svg),
          caption: maps[i].data.caption,
        });
      }
    }

    var section = C.geoelectricSectionGeometry(all, {});
    svg = section.reason ? null : charts.geoelectricSection(section);
    if (svg) {
      made.push({ image: await charts.toPng(svg),
        caption: GEOELECTRIC_SECTION_CAPTION });
    } else {
      notDrawn.push('geoelectric section: ' + figureRefusal(section.reason));
    }

    /* the traverse is built before the pseudo-section, as the report builds
     * it, so a traverse that cannot be placed is the reason printed against
     * the pseudo-section rather than an evenly spaced section drawn under a
     * note saying no positions were recorded */
    var profile = C.traverseProfile(all);
    var pseudo = C.pseudosectionGeometry(soundings || [], profile);
    svg = pseudo.reason ? null : charts.apparentPseudosection(pseudo);
    if (svg) {
      made.push({ image: await charts.toPng(svg),
        caption: C.pseudosectionCaption(C.spacingName(soundings || []), profile) });
    } else {
      notDrawn.push('apparent-resistivity pseudo-section: ' +
        figureRefusal(pseudo.reason));
    }

    /* whether any map in the section has an interpolated surface, for the
     * sentence the section opens on: it promised surfaces over three
     * collinear soundings whose maps had none */
    return { figures: made, notDrawn: notDrawn, anySurface: anySurface };
  }

  /* The drill-target suitability map, mirroring the figure path of
   * reporting/geophysical.py _suitability_block: the scored points on the
   * ground they were surveyed on, coloured by the confidence-weighted score,
   * with the recommended target starred and its grid coordinates beside it,
   * and the caption the state of the figure earns.
   *
   * The engine scores the points from the same assess_siting() the ranked
   * table is built from, so the colour of a peg and the row that ranks it
   * cannot tell a reader two different stories about which peg to drill.
   *
   * Returns null exactly where the Python draws no map - no scored point, or
   * no scored point carrying a recorded position - and the report then says
   * nothing at all, because _suitability_block writes no "not drawn" line for
   * this figure. The subsurface maps below list their refusals; naming this
   * one among them would put a sentence in a client document that the
   * package never writes. A null from the chart layer is the same silence for
   * the same reason: it can only mean a defect in the drawing, and there is
   * no wording for that here which would not read as a refusal the survey
   * earned. */
  async function suitabilityMapFigure(interpretations) {
    var site = store.get('site') || {};
    var data = C.suitabilityMapData(interpretations, {
      ves: config().ves,
      /* site.utm_zone or infer_zone_for_sierra_leone(map_points[0].easting),
       * which is what the engine does for a null zone: two eastings in
       * different zones are not comparable numbers, and a map that does not
       * say which zone it is in cannot be walked back to. */
      zone: site.utm_zone || null,
    });
    if (!data) return null;
    var svg = charts.suitabilityMap(data);
    if (!svg) return null;
    /* the caption travels with the figure because it is a claim about this
     * figure: whether a star marks the target, and whether the colour between
     * the pegs is interpolated ground or no ground at all */
    return { image: await charts.toPng(svg), caption: data.caption };
  }

  /* The ground surface along the traverse, from the level the crew recorded
   * at each sounding: reporting/geophysical.py _ground_profile_figure, drawn
   * with mapping/terrain.py plot_ground_profile.
   *
   * Returns {figure, refusal}. Omitted in silence where the Python omits it -
   * fewer than two soundings carrying a position and an elevation, so there
   * is no profile to be missing. Refused with the engine's reason where the
   * traverse cannot be placed or every gap between levels is wider than the
   * soundings reach, and the reason goes on the "not drawn" list: the
   * profile used to draw Rokel's 71 to 68 m slope across 20.7 km that the
   * section beside it refused. */
  async function groundProfileFigure(interpretations) {
    var data = C.groundProfileData(interpretations);
    if (!data) return { figure: null, refusal: '' };
    if (data.reason) return { figure: null, refusal: data.reason };
    var svg = charts.groundProfile(data);
    if (!svg) return { figure: null, refusal: '' };
    return {
      figure: { image: await charts.toPng(svg), caption: data.caption },
      refusal: '',
    };
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
    /* the document writer, and the maps every report opens on; the page has
     * usually loaded the rest already, but a report can be asked for from
     * anywhere */
    try {
      await need(REPORT_BUNDLES);
    } catch (e) {
      S.toast('Could not build the report: ' + e.message, 'error');
      return;
    }
    /* Every figure this builds goes into a .docx, so it is painted for paper
     * rather than for the theme the app happens to be in; the default theme
     * is dark, and clients were sent maps and drawings on a black ground. */
    charts.usePrintPalette(true);
    try {
      await S.withBusy(host, 'Building the report…', async function () {
        var cfg = config();
        var context = {
          style: cfg.style, site: store.get('site'),
          signOff: signOffFor(kind),
          readiness: reportReadiness(kind),
          issue: issueFor(kind, { photos: reportPhotos(kind) }),
        };
        /* every report opens on where it is; the three reports that argue
         * from the ground carry the aquifer and geology setting too */
        context.areaNote = areaNote();
        context.areaMaps = await areaFigures(
          kind === 'geophysical' || kind === 'completion' || kind === 'handover');
        if (kind === 'pumping' && derived.analysis) {
          context.seasonal = currentSeasonal(derived.analysis);
        }
        var builder;
        var figures = [];

        if (kind === 'geophysical') {
          if (!derived.interpretations || !derived.interpretations.length) {
            throw new Error('No sounding has been interpreted yet.');
          }
          /* The geology paragraph, from the map under the site, through the
           * engine's port of _geology_for. Nothing set it, so every browser
           * report said "crystalline basement" - on the Bullom sands too,
           * beside its own figures showing the Bullom Group and an
           * intergranular aquifer. */
          context.geologyNote = C.geologyParagraph(context.site, siteLatLon());
          for (var i = 0; i < derived.inversions.length; i++) {
            var result = derived.inversions[i];
            /* off the interpretation, which was pushed with this inversion; a
             * sounding that failed to invert is in neither list, so indexing
             * derived.soundings here captioned one sounding's figures with
             * another sounding's name */
            var id = derived.interpretations[i].sounding_id;
            var sampled = rangeFor(result);
            figures.push({
              soundingId: id,
              image: await charts.toPng(charts.vesCurve(result, { hover: false,
                fan: sampled ? sampled.fan_curves : null })),
              caption: 'Sounding curve and fitted model for ' + id +
                (sampled ? '. ' + C.modelRangeCaption(sampled) : ''),
            });
            /* one depth for every figure of this sounding's model, in both
             * engines: the depth of investigation, or deeper where a fitted
             * interface lies below it (ves/plots.py model_depth_m). The panel
             * was drawn to the larger of the depth of investigation and 20 m,
             * a rule no other figure used, under a caption saying it was
             * drawn to the depth of investigation. */
            var doi = derived.interpretations[i].investigation_depth_m;
            /* the fan and the drilling depth's band on the model, as
             * ves/plots.py draws them on its model panel (PLAN.md step 3.6) */
            var drillBand = C.drillingDepthBand(sampled);
            figures.push({
              soundingId: id,
              image: await charts.toPng(charts.layeredModel(result.model, {
                maxDepth: C.modelDepthM(result.model, doi),
                investigationDepth: doi,
                fan: sampled ? sampled.fan : null, drillBand: drillBand,
              })),
              caption: 'Layered earth model for ' + id + ', drawn ' +
                C.drawnDepthText(result.model, doi) + '.' +
                (drillBand ? ' ' + C.drillingBandCaption() : ''), widthCm: 9,
            });
            /* The interpreted layer column, which _sounding_block draws with
             * ves/plots.py plot_model_pseudosection. The staircase above
             * plots resistivity against depth; this is the same model drawn
             * as ground, to scale and coloured on the resistivity bar, and
             * the browser's report had no figure a reader could lay two
             * soundings side by side on. A model with no layers has no column
             * to draw, and the chart layer says so by returning nothing. */
            var layerSection = charts.modelPseudosection(result.model, {
              investigationDepth: doi || null,
              title: 'Layer section at ' + id,
            });
            if (layerSection) {
              figures.push({
                soundingId: id,
                image: await charts.toPng(layerSection),
                caption: 'Interpreted one-dimensional layer section at point ' +
                  id + ': the resistivity and thickness of each fitted layer, ' +
                  'drawn ' + C.drawnDepthText(result.model, doi) + '.',
              });
            }
          }
          /* The study-area map the Python report opens on, ahead of the
           * district locator: it is the only figure in the document that
           * shows the survey points on the ground they were shot on. */
          var studyArea = await studyAreaFigure(derived.interpretations);
          if (studyArea) {
            context.areaMaps = [studyArea].concat(context.areaMaps || []);
          }
          /* The ground the survey was shot on, from the levels the crew
           * recorded: section 3.1 carries it in the Python report, and the
           * browser's report had no figure showing whether the traverse runs
           * up a slope or along a valley floor. Null where the Python draws
           * nothing, and the writer then prints nothing; where the engine
           * refuses it, the reason joins the "not drawn" list below. */
          var ground = await groundProfileFigure(derived.interpretations);
          context.groundProfile = ground.figure;
          /* The drill-target map: the one figure in the document that shows
           * which peg the recommendation is on, rather than naming it. */
          context.suitabilityMap = await suitabilityMapFigure(derived.interpretations);
          /* The soundings this report covers are the ones that inverted,
           * which is the list the Python report holds: inputs.soundings is
           * zipped with the inversions. A sounding that would not invert has
           * no block in the document, so its readings do not belong in the
           * document's pseudo-section either. */
          var interpreted = {};
          derived.interpretations.forEach(function (interp) {
            interpreted[interp.sounding_id] = true;
          });
          var reported = (derived.soundings || []).filter(function (sounding) {
            return interpreted[sounding.sounding_id] === true;
          });
          context.subsurface = await subsurfaceFigures(derived.interpretations,
            reported, ground.refusal);
          /* the soundings carry the instrument and the array the field-work
           * section names and the warnings their sheets raised, which the
           * annex lists; the inversions, in lockstep with the interpretations,
           * carry the array and the models tried */
          context.soundings = reported;
          context.inversions = derived.inversions;
          context.interpretations = derived.interpretations;
          /* the range of each sounding's models, where one was sampled with
           * the settings in force; null where none was */
          context.ranges = derived.inversions.map(rangeFor);
          context.figures = figures;
          context.preferredOrder = store.get('ves.preferredOrder');
          /* the ranked table and the suitability map beside it are scored
           * with the same settings, as reporting/geophysical.py scores them:
           * with the table on the defaults and the figure on the project's,
           * a project carrying a custom fractured-zone resistivity got a
           * table calling one peg first and a star on another, under one
           * heading */
          context.ves = cfg.ves;
          /* the chance of a working borehole at each point, which the
           * report prints under the suitability score */
          context.odds = surveyOdds();
          /* the cost distribution, where the cost has been estimated, which
           * prices one more measurement under the odds (PLAN.md step 3.5) */
          var costed = costSpreads();
          context.costDistribution = costed ? costed.single : null;
          builder = await docx.geophysicalReport(context);

        } else if (kind === 'completion') {
          if (!derived.design) throw new Error('There is no borehole design yet.');
          /* tagged design: true so the writer finds it whatever its caption;
           * a drawing the rules generated is not captioned as-built */
          figures.push({
            image: await charts.toPng(charts.boreholeDesign(derived.design, derived.log)),
            caption: derived.design.as_built
              ? 'As-built borehole record with lithology and construction columns.'
              : 'Borehole construction design generated from the drilling log, ' +
                'with lithology and construction columns.',
            widthCm: 12, design: true,
          });
          GWT.imageSlot.collect(store.get('photos.completion'), 'completion')
            .forEach(function (photo) {
              figures.push({ image: photo, caption: photo.caption, widthCm: 12 });
            });
          context.log = derived.log || {};
          context.design = derived.design;
          /* the completion report's later sections: the test, the
           * installation, the water and what to do about it */
          context.analysis = derived.analysis;
          context.assessment = derived.assessment;
          context.pumpType = store.get('handover.pumpType') || '';
          context.figures = figures;
          /* the bands are worded with the reserve the analysis took */
          context.config = cfg;
          builder = await docx.completionReport(context);

        } else if (kind === 'pumping') {
          if (!derived.analysis) throw new Error('No pumping test has been analysed.');
          figures.push({
            image: await charts.toPng(charts.testOverview(derived.test,
              derived.analysis, { hover: false })),
            caption: 'Water level through the pumping and recovery phases',
          });
          /* the flow regime first, as the report reads it first */
          var diagFig = charts.diagnostic(derived.analysis, { hover: false });
          if (diagFig) figures.push({ image: await charts.toPng(diagFig),
            caption: 'Drawdown and its Bourdet derivative on log-log axes, with ' +
              "the flow regimes the derivative's slope names" });
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
          context.config = cfg;
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
          /* the planning figure beside the bill of quantities (step 3.4) */
          var spreads = costSpreads();
          var marks = C.phraseTable('cost_range.marks');
          if (spreads) {
            context.distribution = spreads.single;
            /* what one more measurement is worth, priced with it (step 3.5) */
            context.measurements = surveyMeasurements(spreads.single);
            context.distributionFigure = {
              image: await charts.toPng(charts.costDistribution(spreads.single.curve,
                costMarks(spreads.single, false), { title: marks.title })),
              caption: C.phrase('cost_range.figure_caption'),
            };
            if (spreads.programme) {
              context.programmeDistribution = spreads.programme;
              context.programmeDistributionFigure = {
                image: await charts.toPng(charts.costDistribution(spreads.programme.curve,
                  costMarks(spreads.programme, true), { title: marks.programme_title })),
                caption: C.phrase('cost_range.programme_figure_caption'),
              };
            }
          }
          context.estimate = derived.estimate;
          context.programme = derived.programme;
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
          /* the photographs the checklist requires, each listed with its
           * provenance and embedded ahead of the general photo plate */
          var evidence = store.get('supervision.evidence') || {};
          context.evidence = items.filter(function (item) {
            return evidence[item.item_id] && evidence[item.item_id].dataUrl;
          }).map(function (item) {
            var photo = evidence[item.item_id];
            figures.push({ image: photo, caption: photo.caption || item.text, widthCm: 12 });
            return { item: item, photo: photo };
          });
          GWT.imageSlot.collect(store.get('photos.supervision'), 'supervision')
            .forEach(function (photo) {
              context.evidence.push({ item: null, photo: photo });
              figures.push({ image: photo, caption: photo.caption, widthCm: 13 });
            });
          context.figures = figures;
          builder = await docx.supervisionReport(context);

        } else if (kind === 'handover') {
          if (derived.design) {
            /* an as-built diagram only when the log records the screens
             * installed; otherwise the design the rules generated */
            figures.push({
              image: await charts.toPng(charts.boreholeDesign(derived.design, derived.log)),
              caption: derived.design.as_built
                ? 'As-built borehole diagram.'
                : 'Borehole construction design generated from the drilling log; ' +
                  'the log records no casing string, so this is not an as-built record.',
              widthCm: 11, design: true,
            });
          }
          GWT.imageSlot.collect(store.get('photos.handover'), 'handover')
            .forEach(function (photo) {
              figures.push({ image: photo, caption: photo.caption, widthCm: 11 });
            });
          /* The record itself, or nothing: the data sheet omits the log
           * block entirely when no drilling log was read, as handover.py
           * does. An empty object here made that guard unfalsifiable, so
           * a project with no log still printed a reference, a depth, a
           * method and a status as six em-dash rows. */
          context.log = derived.log;
          context.design = derived.design;
          context.analysis = derived.analysis;
          context.assessment = derived.assessment;
          context.committee = store.get('handover.committee') || [];
          context.handoverDate = store.get('handover.date') || '';
          /* the maintenance section and the data sheet both follow the pump
           * that was actually installed, so the report has to be told which */
          context.pumpType = store.get('handover.pumpType') || '';
          context.tariffNote = store.get('handover.tariffNote') || '';
          /* the works list names a siting survey only if one was interpreted */
          context.interpretations = derived.interpretations;
          context.figures = figures;
          /* the yield's band is worded with the reserve the analysis took */
          context.config = cfg;
          builder = await docx.handoverReport(context);
        }

        var filename = S.slug(siteLabel()) + '_' + kind + '_report.docx';
        /* saved first: the builder has no record until it has built the document */
        var reportBytes = await builder.save(filename);
        recordIssue(builder.record, filename, reportBytes);
        /* what the report predicts goes into the ledger as it is issued */
        if (kind === 'geophysical') recordSurveyPredictions();
        S.toast(savedWords(filename, builder.record), 'ok');
      });
    } catch (e) {
      S.toast('Could not build the report: ' + e.message, 'error');
      console.error(e);
    } finally {
      charts.usePrintPalette(false);
    }
  }

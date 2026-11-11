
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
          button('Re-run inversion', function () { invertAndShow(false); },
            { variant: 'ghost' }),
          derived.inversions && derived.inversions.length && !working('range')
            ? button('Sample the range of models', function () { sampleRanges(); }, {
              variant: 'ghost',
              title: 'Sample the models that fit each sounding about as well as ' +
                'its best fit, for the P10 to P90 of basement, the weathered zone ' +
                'and the drilling depth; a few seconds a sounding',
            }) : null,
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
      nodes.push(working('invert')
        ? S.empty('Inverting the soundings. Their models appear here when the ' +
          'inversion finishes; the bar above shows how far it has got, and the ' +
          'rest of the workspace can be used meanwhile.')
        : S.empty('The soundings are loaded but not yet inverted.',
          button('Invert now', function () { invertAndShow(true); })));
      return nodes;
    }

    /* A sounding that would not invert is only ever announced by a toast, which
     * is gone by the time anyone reads the page. Say on the page which ones are
     * missing: a survey reported on four soundings when five were shot is a
     * different survey, and the reader cannot tell from the figures alone. */
    var interpretedIds = derived.interpretations.map(function (interp) {
      return interp.sounding_id;
    });
    var uninterpreted = (derived.soundings || []).filter(function (sounding) {
      return interpretedIds.indexOf(sounding.sounding_id) < 0;
    });
    if (uninterpreted.length) {
      nodes.push(el('div.callout.callout-warn', [
        el('p', el('strong', uninterpreted.length + ' ' +
          S.plural(uninterpreted.length, 'sounding') + ' could not be interpreted')),
        el('p', S.joinList(uninterpreted.map(function (s2) { return s2.sounding_id; })) +
          '. Nothing below is drawn from ' +
          (uninterpreted.length === 1 ? 'it' : 'them') + ', and the geophysical ' +
          'report will not carry ' + (uninterpreted.length === 1 ? 'it' : 'them') +
          '. Check the readings on the field sheet and reload.'),
      ]));
    }

    /* The id comes off the interpretation, not out of derived.soundings by the
     * same index. A sounding that will not invert is not pushed to either list,
     * so the lists are shorter than the soundings and every index past the
     * failure points at the wrong sounding: the next sounding's curve, model
     * and interpretation appear under the failed one's name, and the last
     * sounding disappears. An inversion and its interpretation are pushed
     * together, so reading the name off the interpretation cannot drift. */
    derived.inversions.forEach(function (result, i) {
      var interp = derived.interpretations[i];
      var soundingId = interp.sounding_id;
      var range = rangeFor(result);
      var curve = charts.vesCurve(result, { fan: range ? range.fan_curves : null });
      /* the depth every figure of this model is drawn to, the report's too */
      var model = charts.layeredModel(result.model, {
        maxDepth: C.modelDepthM(result.model, interp.investigation_depth_m),
        investigationDepth: interp.investigation_depth_m,
        /* the fan and the drilling depth's band, as the report draws them */
        fan: range ? range.fan : null, drillBand: C.drillingDepthBand(range),
      });
      nodes.push(card(soundingId + ' — ' +
        C.describeCurveType(interp.curve_type).split(';')[0], [
        S.statRow([
          S.stat('Fit error', result.fit_error_percent.toFixed(1) + '%',
            result.model.n_layers + ' layers, ' + result.n_iterations + ' iterations'),
          S.stat('Depth to bedrock', interp.depth_to_basement_m !== null
            ? C.fmtNum(interp.depth_to_basement_m) + ' m' : 'not resolved'),
          S.stat('Aquifer thickness', C.fmtNum(interp.aquifer_thickness_m) + ' m',
            interp.water_zones.length + ' ' +
            S.plural(interp.water_zones.length, 'zone')),
          S.stat('Max drilling depth', C.drillingDepthText(interp),
            interp.basement_not_resolved
              ? 'a minimum: the zone continues below the depth of investigation'
              : 'capped at the depth of investigation'),
          S.stat('Protective capacity', interp.protective_capacity,
            'S = ' + C.fmtNum(interp.protective_conductance_s, 3) + ' S'),
        ]),
        el('div.split.split-figure', [
          charts.figure(curve, 'Sounding curve for ' + soundingId, {
            filename: 'ves_' + S.slug(soundingId),
            table: function () {
              return S.table([
                { key: 'ab2',
                  label: String(result.array_type || '').indexOf('wenner') === 0
                    ? 'a (m)' : 'AB/2 (m)',
                  align: 'right' },
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
          charts.figure(model, 'Layered model for ' + soundingId,
            { filename: 'model_' + S.slug(soundingId) }),
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
        /* the range beside the best fit, never in place of it */
        range ? el('div.callout.callout-info', [
          el('p', el('strong', 'Range of models that fit')),
          el('p', C.modelRangeText(range).join(' ')),
          S.table(['', 'P10', 'P50', 'P90'], C.modelRangeRows(range)),
          el('p.muted', C.modelRangeCaption(range)),
        ]) : null,
        result.rho_uncertainty_factor ? el('p.muted',
          'The ×/÷ figures are the one-sigma multiplicative uncertainty on each ' +
          'resistivity: a factor near 1 is well resolved, a large one marks the ' +
          'equivalence that makes resistivity models non-unique.') : null,
      ]));
      /* #/ves/<sounding> opens on this card */
      itemNode(soundingId, nodes[nodes.length - 1]);
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
            C.rankInterpretations(derived.interpretations, store.get('ves.preferredOrder'),
              config().ves);
            render();
          })),
    ]));

    var suitability = C.assessSiting(derived.interpretations, config().ves);
    /* the chance of a working borehole beside the score (PLAN.md step 3.3),
     * paired with its row by position: two points can share an id */
    var odds = surveyOdds();
    suitability = suitability.map(function (s) {
      return Object.assign({}, s, { odds: odds[s.index] ? C.oddsShort(odds[s.index]) : '' });
    });
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
        { key: 'odds', label: C.phrase('odds.col_short') },
        { key: 'grade', label: 'Grade' },
        { key: 'rationale', label: 'Why' },
      ], suitability, {
        rowClass: function (row) { return row.rank === 1 ? 'row-ok' : ''; },
      }),
      el('h3', C.phrase('odds.heading')),
      el('p.muted', [C.phrase('odds.lead')].concat(odds[best.index]
        ? C.oddsBasisText(odds[best.index]) : []).join(' ')),
      el('div.odds-points', suitability.map(function (s) {
        var o = odds[s.index];
        if (!o) return null;
        return el('div.odds-point', [
          el('p', [el('strong', s.sounding_id + ': '), C.oddsPointText(o).join(' ')]),
          S.table(C.oddsHeader(), C.oddsRows(o)),
          el('p.muted', C.oddsTableCaption(o)),
        ]);
      }).filter(Boolean)),
      /* what one more measurement at the first-ranked point is worth
       * (PLAN.md step 3.5), once the cost has been estimated */
      el('h3', C.phrase('measurement.heading')),
      el('div.measurements', (function () {
        var costed = costSpreads();
        return costed ? measurementNodes(surveyMeasurements(costed.single))
          : [el('p.muted', [C.phrase('measurement.lead'),
            C.phrase('measurement.no_cost')].join(' '))];
      })()),
      located.length ? charts.figure(charts.siteMap({
        context: (mapLayers().chiefdomBoundaries || {}).features || [],
        points: located.map(function (s) {
          var ll = utmToLatLon(s.easting, s.northing,
            store.get('site.utm_zone') || C.inferZoneForSierraLeone(s.easting));
          if (!ll) return null;
          return {
            lon: ll.lon, lat: ll.lat, label: s.sounding_id,
            size: 4 + s.suitability / 25,
            colour: s.suitability >= 75 ? charts.mapPalette().good
              : (s.suitability >= 55 ? charts.mapPalette().cat[2]
                : (s.suitability >= 35 ? charts.mapPalette().warning
                  : charts.mapPalette().critical)),
          };
        }).filter(Boolean),
        title: 'Drill-target suitability',
        legendItems: [
          { label: 'Very good', colour: charts.mapPalette().good },
          { label: 'Good', colour: charts.mapPalette().cat[2] },
          { label: 'Moderate', colour: charts.mapPalette().warning },
          { label: 'Poor', colour: charts.mapPalette().critical },
        ],
        width: 640, height: 520,
      }), 'Candidate points scored for drilling', { filename: 'suitability_map' })
        : el('p.muted', 'Add GPS coordinates to the VES points to draw the ' +
          'drill-target map.'),
    ]));

    nodes.push(ledgerCard());

    nodes.push(reportCard('Geophysical survey report', 'geophysical',
      'Introduction, geology, field work, per-sounding interpretation, the ranked ' +
      'preference table, conclusions and the limitations of the method.'));

    nodes.push(nextStep('With a target chosen, set out the borehole construction.',
      'Borehole design', 'design'));
    return nodes;
  };

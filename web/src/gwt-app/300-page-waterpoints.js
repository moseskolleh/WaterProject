
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
          var skipped = [];
          var points = C.parseWpdxRecords(raw, skipped);
          derived.waterPointsSkipped = skipped;
          if (spec.clip) {
            points = C.pointsWithin(points, spec.lat, spec.lon, spec.radiusM);
          }
          derived.waterPoints = points;
          derived.waterPointsSource = spec.label;
          derived.waterPointsRadius = spec.clip ? spec.radiusM : null;
          derived.waterPointsCentre = spec.clip ? { lat: spec.lat, lon: spec.lon } : null;
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
    /* What the reader threw away belongs next to what it kept. An export that
     * is half unusable and a complete one both come back as a number of water
     * points, and that number is what decides whether a community here reads
     * as served or unserved.
     *
     * The count and the discards are reported independently, because the case
     * that matters most is the one where they disagree hardest: a BOM'd CSV
     * whose first column arrives as "\ufefflat_deg" loses every coordinate, so
     * the page has nothing to count and everything to explain. Hanging the
     * whole note on points.length hid the explanation in exactly that case and
     * left "no water points near this site" - the opposite of what the export
     * says. */
    var points = derived.waterPoints || [];
    var skipped = derived.waterPointsSkipped || [];
    if (!points.length && !skipped.length) return null;
    var source = derived.waterPointsSource ?
      ' (' + derived.waterPointsSource + ')' : '';
    return el('div', [
      points.length ? el('p.muted', [
        S.thousands(points.length) + ' water points loaded' + source + '. ' +
        C.WPDX_CREDIT,
      ]) : el('p.muted', [
        'No usable water point came back from this inventory' + source + '. ' +
        C.WPDX_CREDIT,
      ]),
      skipped.length ? el('p.muted', skipped.map(function (flag) {
        return flag.message;
      }).join(' ')) : null,
    ].filter(Boolean));
  }

  /* The radius the water points held were searched within: a site lookup's
   * own, which it clipped them to, else the box's (a CSV or the national
   * pull covers any radius). The box changed after a lookup used to be
   * quoted over the points the lookup kept, so the desk study said "no
   * water point within 2,000 m" beside a borehole 1.5 km off that a 500 m
   * lookup never loaded. The Python app quotes the lookup's radius too. */
  function waterPointsSearchRadius() {
    var held = derived.waterPointsRadius;
    return held === null || held === undefined
      ? store.get('waterpoints.radius', C.DEFAULT_SEARCH_RADIUS_M) : held;
  }

  /* How far round `site` ({lat, lon}) the water points held were looked up,
   * for the survey plan: a lookup's radius, less how far the site now lies
   * from where the lookup was centred; null where they are not cut to a
   * circle round the site. app/views/site_maps._water_points_searched. */
  function waterPointsSearched(site) {
    var held = derived.waterPointsRadius, centre = derived.waterPointsCentre;
    if (held === null || held === undefined || !derived.waterPoints) return null;
    if (!centre || !site) return held;
    return Math.max(0, held - C.geodesicDistanceM(centre.lat, centre.lon, site.lat, site.lon));
  }

  PAGES.waterpoints = function () {
    var latlon = siteLatLon();
    var points = derived.waterPoints || [];
    var radius = store.get('waterpoints.radius', C.DEFAULT_SEARCH_RADIUS_M);
    var searched = waterPointsSearchRadius();
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
              var csvSkipped = [];
              derived.waterPoints = C.parseWpdxRecords(S.parseCsv(text), csvSkipped);
              derived.waterPointsSkipped = csvSkipped;
              derived.waterPointsSource = file.name;
              derived.waterPointsCapped = false;
              derived.waterPointsRadius = null; derived.waterPointsCentre = null;
              S.toast(derived.waterPoints.length + ' water points read.', 'ok');
              render();
            } catch (e) {
              S.toast('Could not read that CSV: ' + e.message, 'error');
            }
          }, { variant: 'ghost' }),
          points.length ? button('Clear', function () {
            derived.waterPoints = null; derived.waterPointsSource = null;
            derived.waterPointsCapped = false; derived.waterPointsRadius = null;
            derived.waterPointsCentre = null; derived.waterPointsSkipped = null; render();
          }, { variant: 'ghost' }) : null,
        ]),
        !latlon ? el('p.muted', 'The live lookup needs the site GPS position; ' +
          'set it on the Site page. A CSV export can be analysed without one.') : null,
        derived.waterPointsCapped ? el('div.callout.callout-warn', el('p',
          'The lookup hit its row cap, so this is a partial slice of the area. ' +
          'Narrow the radius, or use a filtered CSV export for a complete, ' +
          'reproducible analysis.')) : null,
        searched !== radius ? el('p.muted', { 'data-searched': String(searched) },
          'These water points were looked up within ' + S.thousands(Math.round(searched)) +
          ' m of the site, and everything below speaks of that radius: press Look up water points ' +
          'to search ' + S.thousands(Math.round(radius)) + ' m.') : null,
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
        { searchRadiusM: searched });
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
          context: (mapLayers().chiefdomBoundaries || {}).features || [],
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
          : S.empty('Nothing mapped within ' + Math.round(searched) + ' m of the site.'),
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

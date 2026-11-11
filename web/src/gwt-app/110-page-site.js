
  /* --- site & maps ---------------------------------------------------------- */

  /* Held outside the render so the field keeps what was typed while the page
   * redraws around it. Cleared when the page is drawn fresh, so a stale
   * value cannot be converted after the input has visibly reset. */
  var latLonEntry = { text: '' };

  /* "lat, lon" as a field crew writes it: the pair, or null where the text
   * was refused.
   *
   * The reading itself is the engine's - C.readLatLon, a port of geo.py - so
   * that the browser and the Python toolkit make the same sense of the same
   * pasted string, including when they refuse it. It reads a hemisphere
   * letter as a sign, reads degrees and minutes as degrees and minutes, and
   * carries the reason for a refusal and the assumption behind a reading
   * back with the numbers. Anything an operator sees uses that reading; this
   * wrapper is for the callers that want only the pair. */
  function parseLatLon(text) {
    var reading = C.readLatLon(text);
    if (reading.lat === null || reading.lon === null) return null;
    return { lat: reading.lat, lon: reading.lon };
  }

  /* "lat, lon" converted into the site's UTM fields: what the paste box's
   * Convert does, and what the degree callout does with the pair typed into
   * the two boxes. */
  function convertLatLon(text) {
    var reading = C.readLatLon(text);
    if (reading.lat === null || reading.lon === null) {
      /* What the parser refused, and why, is what the operator needs:
       * "8 27.942" is two readings 2000 km apart and the sentence says so,
       * where a single generic line said only that something was wrong. */
      S.toast(reading.message + " Enter 'lat, lon' in decimal " +
        'degrees - 8.4657, -13.2317 or 8.4657 N, 13.2317 W - or in ' +
        'degrees and minutes, 8 27.942 N, 13 13.902 W.', 'error');
      return;
    }
    var lat = reading.lat, lon = reading.lon;
    var utm = C.geographicToUtm(lat, lon);
    if ((utm.zone !== 28 && utm.zone !== 29) || utm.hemisphere !== 'N') {
      /* The site fields hold Sierra Leone's two zones. Writing this easting
       * down beside 28N or 29N would relabel the position rather than
       * convert it, and land the site inside the country: an unsigned
       * 13.2317 projected in zone 33 was stored here as a zone-33 easting,
       * 270 km east of Freetown, with nothing said (ROADMAP
       * data-ingestion-3). */
      S.toast(C.pyFixed(lat, 4) + ', ' + C.pyFixed(lon, 4) +
        ' falls in UTM zone ' + utm.zone + utm.hemisphere +
        ", outside Sierra Leone's 28N and 29N, so it cannot be " +
        'stored as a site position. Check the coordinates - a ' +
        'western longitude needs its minus sign or its W.', 'error');
      return;
    }
    store.set('site.easting', S.round(utm.easting, 1));
    store.set('site.northing', S.round(utm.northing, 1));
    store.set('site.utm_zone', utm.zone);
    S.toast('Converted to UTM zone ' + utm.zone + 'N.', 'ok');
    if (reading.message) {
      /* The position was converted, but on a sign the parser supplied
       * rather than one the crew typed, so it is said out loud rather than
       * left inside the reading. */
      S.toast(reading.message, 'warn');
    }
    render();
  }

  PAGES.site = function () {
    var site = store.get('site');
    var mapRadius = store.get('site.mapRadiusKm', 40);
    /* the input below is rendered empty every time, so the buffer behind it
     * must be too — otherwise Convert acts on text the operator can no
     * longer see */
    latLonEntry.text = '';
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
    /* degrees typed into the two boxes: no position until converted */
    var degreeBoxes = C.degreesInUtmBoxes(site.easting, site.northing);
    var districtWarning = districtNote(site, latlon);
    var mapNode = null;
    if (mapLayers() && mapLayers().adminBoundaries) {
      var boundaries = mapLayers().adminBoundaries.features || [];
      var home = locatorHome(site, latlon);
      var legendItems = [];
      if (latlon) {
        legendItems.push({ label: 'Project site', kind: 'diamond',
          colour: charts.mapPalette().secondary });
      }
      if (home.legend) legendItems.push(home.legend);
      legendItems.push({ label: 'other districts', colour: OTHER_FILL });
      mapNode = charts.siteMap({
        context: boundaries,
        /* the bundled layer is geoBoundaries; the credit named a dataset this
         * repository does not carry, and the map had no sea or neighbours to
         * tell the Atlantic from unmapped ground */
        outline: nationalOutline(mapLayers()),
        labelContext: true,
        contextFill: home.fill,
        highlight: home.highlight, highlightFill: HOME_FILL,
        highlightLabel: home.highlight.length ? home.name : '',
        points: latlon ? [{
          lon: latlon.lon, lat: latlon.lat, label: siteLabel(),
          colour: charts.mapPalette().secondary, size: 6.5,
        }] : [],
        title: 'Site location',
        legendItems: legendItems,
        credit: 'District boundaries: geoBoundaries (CC BY 4.0).',
        width: 620, height: 560,
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
          /* Metres only. These used to invite a longitude and a latitude in
           * degrees, which this app read as degrees and the Python engine as
           * metres near the equator: one project, a placard the gate passed
           * and an identifier nobody could mint. Degrees typed here are now
           * refused by both engines, and the callout below offers to convert
           * them. */
          field('GPS easting (UTM m)', S.numberInput(site.easting, bindNum('easting'))),
          field('GPS northing (UTM m)', S.numberInput(site.northing, bindNum('northing'))),
          field('UTM zone', S.selectInput(site.utm_zone || '',
            [{ value: '', label: 'infer from the easting' },
              { value: '28', label: '28N' }, { value: '29', label: '29N' }],
            function (v) { store.set('site.utm_zone', v ? Number(v) : null); render(); })),
          field('Elevation (m)', S.numberInput(site.elevation_m, bindNum('elevation_m'))),
          field('Date', S.textInput(site.date, bind('date'))),
        ]),
        /* degrees typed into the two boxes, said in the words the gate and
         * the identifier use, with the conversion offered */
        degreeBoxes ? el('div.callout.callout-warn', [
          el('p', degreeBoxes),
          el('div.btn-row', [button('Convert these degrees to UTM', function () {
            /* the operator saying the boxes hold degrees: read exactly as a
             * pasted pair is, so an unsigned longitude is west, and said */
            convertLatLon(String(Number(site.northing)) + ', ' +
              String(Number(site.easting)));
          }, { variant: 'ghost' })]),
        ]) : null,
        /* Field crews read decimal degrees off a phone or a handheld GPS.
         * Pasting them here removes the UTM-conversion friction and the
         * wrong-zone errors that come with it. */
        field('or paste "lat, lon" from a phone or handheld GPS',
          el('div.btn-row', [
            S.textInput('', function (value) { latLonEntry.text = value; },
              { placeholder: '8.4657, -13.2317' }),
            button('Convert to UTM', function () {
              convertLatLon(latLonEntry.text);
            }, { variant: 'ghost' }),
          ])),
        latlon ? el('p.muted', 'Interpreted position: ' + degreesText(latlon) +
          ' (converted from UTM zone ' + latlon.zone + ')' +
          (latlon.chiefdom ? ' — inside ' + latlon.chiefdom + ' chiefdom' +
            (districtOf(latlon.chiefdom) ? ', ' + districtOf(latlon.chiefdom) +
              ' district' : '') : '')) : null,
        /* a position outside the country is on no map below: it is said
         * where the position is shown, in the words the engine uses */
        latlon && latlon.outside
          ? el('div.callout.callout-bad', el('p', latlon.outside)) : null,
        /* the commonest copy-over error on a field sheet is a district that
         * does not contain the recorded position, so say so where it is seen */
        districtWarning
          ? el('div.callout.callout-warn', el('p', districtWarning)) : null,
      ]),

      mapNode ? card('Where the site sits', [
        charts.figure(mapNode, 'Project location within Sierra Leone',
          { filename: 'site_location' }),
        el('p.muted', C.POPULATION_CREDIT),
      ]) : null,

      studyAreaNode() ? card('Study area', [
        el('p.muted', 'The study area at a scale where the distances can be ' +
          'read off the scale bar: the chiefdom boundaries around the site, ' +
          'the survey points and any water points already found, with a ' +
          'thumbnail of the country showing where in it this is. It is the ' +
          'map the geophysical survey and handover reports open on.'),
        charts.figure(studyAreaNode(), 'Study area with its location in ' +
          'Sierra Leone inset. Boundaries from geoBoundaries (CC BY 4.0).',
          { filename: 'study_area_map' }),
      ]) : null,

      card('Geology and aquifers', [
        el('p.muted', 'Report-ready context from freely licensed datasets: ' +
          'geology from the USGS Geologic Map of Africa, and aquifer type and ' +
          'productivity from the BGS Africa Groundwater Atlas. These are the ' +
          'same layers the geophysical survey and handover reports carry.'),
        latlon ? field('Local map window (km around the site)',
          S.numberInput(mapRadius, function (value) {
            store.set('site.mapRadiusKm', S.clamp(Number(value) || 40, 5, 400));
            render();
          }, { min: 5, max: 400, step: 5 })) : el('p.muted',
          'Without site coordinates the national maps are drawn unmarked; ' +
          'enter a position above for the local window.'),
        el('div.grid.grid-2', [
          charts.figure(charts.thematicMap({
            features: (mapLayers().hydrogeology || {}).features || [],
            context: (mapLayers().adminBoundaries || {}).features || [],
            key: 'unit',
            window: latlon ? { lat: latlon.lat, lon: latlon.lon, radiusKm: mapRadius } : null,
            points: latlon ? [{ lon: latlon.lon, lat: latlon.lat, label: siteLabel() }] : [],
            title: latlon ? 'Aquifer productivity around the site'
              : 'Aquifer productivity, Sierra Leone',
            credit: 'BGS Africa Groundwater Atlas, CC BY-SA 4.0.',
            sourceScale: charts.bgsSourceScale,
            publisherNote: charts.bgsPublisherNote,
            legendTitle: 'AQUIFER TYPE AND PRODUCTIVITY',
            // the BGS colours ARE the classification, so they stay
            sourceColours: true,
            outline: nationalOutline(mapLayers()),
            width: 560, height: 680,
          }), 'Aquifer type and productivity (BGS Africa Groundwater Atlas, CC BY-SA 4.0)',
          { filename: 'aquifer_map' }),
          charts.figure(charts.thematicMap({
            features: (mapLayers().geology || {}).features || [],
            context: (mapLayers().adminBoundaries || {}).features || [],
            key: 'unit',
            window: latlon ? { lat: latlon.lat, lon: latlon.lon, radiusKm: mapRadius } : null,
            points: latlon ? [{ lon: latlon.lon, lat: latlon.lat, label: siteLabel() }] : [],
            title: latlon ? 'Geology around the site' : 'Geology, Sierra Leone',
            credit: 'USGS Geologic Map of Africa. Lithology: Geology of ' +
              'Sierra Leone (Fileccia et al. 2017, MoWR/SALWACO, 1:600,000).',
            legendTitle: 'GEOLOGICAL UNIT',
            sourceScale: charts.usgsSourceScale,
            outline: nationalOutline(mapLayers()),
            nameLithology: true, district: store.get('site.district') || '',
            width: 560, height: 680,
          }), 'Geology (USGS Geologic Map of Africa)', { filename: 'geology_map' }),
        ]),
      ]),

      terrainCard(),

      card('Interactive map', [
        el('p.muted', 'The maps above are pictures, which is what a report ' +
          'needs. This writes the same survey as a GeoLibre project file — an ' +
          'open, plain-JSON map format — so it can be panned, zoomed, clicked ' +
          'and put over satellite imagery instead. GeoLibre is free and open ' +
          'source, and the file opens in its web app, its desktop app, its ' +
          'phone apps and in a Jupyter notebook. Nothing is uploaded: the ' +
          'project is assembled in this page and saved to this machine. With ' +
          'a GPS fix it also draws the separation distances as rings round ' +
          'the wellhead: the ground a latrine, a burial ground or another ' +
          'well has to stay out of. The Python app also keeps each ' +
          'continuous surface clipped to the surveyed ground, and the ' +
          'drill-target score, as a GeoTIFF for a GIS; this page draws the ' +
          'surfaces only as pictures.'),
        el('div.btn-row', [
          button('Save GeoLibre project', function () {
            saveGeolibreProject();
          }, { variant: 'primary' }),
          el('a.btn.btn-ghost', {
            href: GWT.geolibre.WEB_APP, target: '_blank', rel: 'noopener',
          }, 'Open GeoLibre'),
        ]),
        el('p.muted', 'Open GeoLibre and use Project → Open on the saved file, ' +
          'or drag it onto the map. A file on this machine has no address, so ' +
          'there is no link that can carry it; publish the project somewhere ' +
          'and it opens directly from a link.'),
        el('p.muted', 'The project opens on a blank background rather than a ' +
          'basemap: switching one on is the first request it makes to the ' +
          'network, and that is your decision rather than this app\'s. Layer ' +
          'attributions travel inside the file — the aquifer layer is ' +
          'CC BY-SA 4.0, so a project carrying it inherits ShareAlike.'),
      ]),

      deskStudyCard(),

      nextStep('With the site recorded, upload the geophysical survey to choose ' +
        'the drilling point.', 'Geophysics', 'ves'),
    ];
  };

  /* Everything a GeoLibre project needs is already in the page: the site,
   * the drill targets scored from the soundings, any water points that have
   * been loaded, and the bundled boundary, geology and aquifer layers. This
   * gathers them; gwt-geolibre.js knows what to do with them. */
  function saveGeolibreProject() {
    var latlon = siteLatLon();
    var site = store.get('site') || {};
    /* Without a GPS fix the chiefdom, or failing that the district, is
     * still an area worth opening on - the same resolution the local
     * geology and aquifer maps use. With none of the three there is
     * nothing to centre on, and the bundled layers alone would write a
     * megabyte of Sierra Leone with the site missing from it. */
    var area = areaWindow(store.get('site.mapRadiusKm') || 40);
    if (!area) {
      S.toast('Enter the site coordinates, or its chiefdom or district — a ' +
        'project with no position has nothing to centre on.', 'warn');
      return;
    }
    var geo = mapLayers() || {};
    var interpretations = (derived || {}).interpretations || [];
    var zone = site.utm_zone ||
      (site.easting ? C.inferZoneForSierraLeone(site.easting) : null);
    var project = GWT.geolibre.saveForSite({
      community: site.community, chiefdom: site.chiefdom,
      district: site.district, client: site.client, project: site.project,
      lat: latlon ? latlon.lat : null,
      lon: latlon ? latlon.lon : null,
      zone: zone,
      area: area,
      /* Scores are in projected metres. Without a zone they cannot be
       * placed, and guessing one puts half the country in the Atlantic. */
      suitability: (interpretations.length && zone != null)
        ? C.assessSiting(interpretations, config().ves) : null,
      waterPoints: (derived || {}).waterPoints || null,
      chiefdoms: geo.chiefdomBoundaries, geology: geo.geology,
      hydrogeology: geo.hydrogeology,
      windowKm: Number(store.get('site.mapRadiusKm')) || 40,
    });
    S.toast(project.layers.length + ' layers saved as a GeoLibre project' +
      (area.exact ? '.' : ', centred on ' + area.label +
        ' — this site has no GPS fix, so no position is marked.'), 'ok');
  }

  /* Sierra Leone lies in UTM zones 28N and 29N; the easting alone identifies
   * the zone, so it is inferred rather than guessed. A pair of small numbers
   * typed into the two boxes is degrees and no position at all, in both
   * engines (C.degreesInUtmBoxes): the site page says so and offers to
   * convert it, reading it the way a pasted "lat, lon" is read, so a
   * longitude typed without its western sign is read as west and the
   * reading says so. It was read as degrees here and as metres by the
   * Python engine, which put the same project 940 km apart.
   *
   * `outside` is the sentence check_site_consistency writes for a position
   * outside the country; the site page shows it. */
  function siteLatLon() {
    /* read once, in the core, so the readiness gate refuses the position the
     * site page flags */
    var ll = C.sitePosition(store.get('site'));
    if (!ll) return null;
    ll.outside = C.outsideCountryNote(ll.lat, ll.lon);
    ll.chiefdom = chiefdomAt(ll.lat, ll.lon);
    return ll;
  }

  /* A position as a reader writes it: "8.46570° N, 13.23170° W". The site
   * page printed the signed longitude against an E, so a correct western fix
   * read "-13.23170°E". */
  function degreesText(latlon) {
    return C.pyFixed(Math.abs(latlon.lat), 5) + '° ' + (latlon.lat >= 0 ? 'N' : 'S') +
      ', ' + C.pyFixed(Math.abs(latlon.lon), 5) + '° ' + (latlon.lon >= 0 ? 'E' : 'W');
  }

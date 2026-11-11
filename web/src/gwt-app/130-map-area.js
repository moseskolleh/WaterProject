
  /* --- the area a report should map ---------------------------------------
   *
   * Every report is about a place, so every report carries a map of it. A GPS
   * fix gives a point. Without one, the recorded chiefdom or district still
   * gives an area, and an area is what most of these maps are really asked
   * for: where in the country this is, and what the ground is like around it.
   * Only a project that records neither gets no map, and then the report says
   * so rather than leaving a gap.
   *
   * The window itself is the engine's C.areaWindow, a port of
   * groundwater.mapping.area_window held to it by the parity suite, so the
   * browser report and the report the desktop toolkit writes cover the same
   * ground at the same size. The page used to work it out with rules of its
   * own - the largest ring only, the layer's truncated chiefdom names, a
   * district name compared as typed - and gave Dema a window a third
   * narrower than the Python's, no map at all for Karene, Falaba, "Western
   * Area" or "Port Loko District", and "Bureh Kasseh Ma chiefdom" in a
   * caption.
   */

  /* The district a location map lights, and the legend entry that names it.
   * The fill is applied to the polygons C.homeDistrict names, and to the
   * chiefdoms it names in place of a district the boundary layer predates;
   * the legend names the district only when something is lit, because a key
   * entry in a colour that is nowhere on the map is a key that lies. */
  var HOME_FILL = '#CFE0D6';
  var OTHER_FILL = '#EDEAE3';

  function locatorHome(site, latlon) {
    var home = C.homeDistrict(site, latlon);
    var lit = {};
    home.chiefdoms.forEach(function (name) { lit[name] = true; });
    var chiefdoms = (((mapLayers() || {}).chiefdomBoundaries || {}).features || [])
      .filter(function (f) { return lit[(f.properties || {}).name] === true; });
    return {
      name: home.name,
      fill: function (feature) {
        var props = feature.properties || {};
        var name = String(props.name || props.shapeName || '').trim().toLowerCase();
        return home.districts.indexOf(name) >= 0 ? HOME_FILL : OTHER_FILL;
      },
      highlight: chiefdoms,
      legend: home.districts.length || chiefdoms.length
        ? { label: C.districtLabel(home.name), colour: HOME_FILL } : null,
    };
  }

  /* The national outline on its own. The geology and aquifer maps need it
   * to tell sea from a hole in the source layer, and to drop units that
   * lie wholly across the border. */
  function nationalOutline(geo) {
    return (((geo || {}).adminBoundaries || {}).features || []).filter(
      function (f) { return (f.properties || {}).level === 'ADM0'; });
  }

  /* The study area map for the Site page and the reports. Everything it
   * needs is already in the page: the window the local maps use, the
   * bundled boundary layers, the soundings and any water points loaded. */
  /* `surveyOnly` draws the figure the geophysical report carries: the
   * soundings and the star, and nothing else. reporting/geophysical.py builds
   * its own overlay from the soundings alone and passes mark_site=False, on
   * the reasoning that a siting map must carry one unmistakable marker - the
   * recommended point. The page's own map still shows the site and any water
   * points that have been looked up; the report's did too, so an operator who
   * had run the Water points page got up to forty of them scattered over
   * Figure 1 of a survey report. */
  function studyAreaNode(options) {
    var surveyOnly = (options || {}).surveyOnly;
    var window_ = areaWindow(store.get('site.mapRadiusKm', 40));
    if (!window_) return null;
    var geo = mapLayers() || {};
    var points = [];
    /* two points the ranking cannot separate get no star between them, as on
     * the drill-target map: the report's text calls them indistinguishable */
    var tie = surveyTie(derived.interpretations);
    (derived.interpretations || []).forEach(function (interp) {
      var pos = soundingLatLon(interp);
      if (pos) {
        points.push({ lat: pos.lat, lon: pos.lon, label: interp.sounding_id,
          kind: interp.rank === 1 && !tie ? 'recommended point' : 'VES point' });
      }
    });
    /* the site marker, unless it would sit on a sounding: a siting survey's
     * "site" is the first sounding's position, and a marker drawn over it
     * read as "drill here" on whichever peg was first on the sheet */
    var onASounding = points.some(function (p) {
      return Math.abs(p.lat - window_.lat) < 1e-6 && Math.abs(p.lon - window_.lon) < 1e-6;
    });
    if (window_.exact && !onASounding && !surveyOnly) {
      points.push({ lat: window_.lat, lon: window_.lon, label: siteLabel(),
        kind: derived.log ? 'borehole' : 'site' });
    }
    /* the water points the Water points page looked up, if it has run */
    (surveyOnly ? [] : (derived.waterPoints || [])).slice(0, 40).forEach(function (wp) {
      if (typeof wp.lat === 'number' && typeof wp.lon === 'number') {
        points.push({ lat: wp.lat, lon: wp.lon, kind: 'water point' });
      }
    });
    return charts.studyAreaMap({
      window: window_,
      outline: nationalOutline(geo),
      districts: ((geo.adminBoundaries || {}).features || []).filter(
        function (f) { return (f.properties || {}).level !== 'ADM0'; }),
      areas: (geo.chiefdomBoundaries || {}).features || [],
      points: points,
      title: 'Study area — ' + window_.label +
        (window_.exact ? '' : ' (no site position recorded)'),
      credit: 'Boundaries: geoBoundaries, CC BY 4.0 (predates the 2017 ' +
        'Karene and Falaba districts).',
      legendTitle: 'ON THE MAP',
      width: 620, height: 560,
    });
  }

  /* The survey's one tie, as reporting/geophysical.py computes it once for the
   * whole document: rankingTie() over the scorecard, on the project's own
   * ranking_tie_points. The study-area map, the drill-target map and their
   * captions all read it, where each map used to decide it again. */
  function surveyTie(interpretations) {
    if (!interpretations || !interpretations.length) return false;
    var ves = config().ves;
    return C.rankingTie(C.assessSiting(interpretations, ves),
      ves.ranking_tie_points) !== '';
  }

  /* A sounding carries its own position, which is not always the site's:
   * a traverse is a line of pegs, and the map is the only place that shows
   * which end of it the drill target sits at. */
  function soundingLatLon(interp) {
    if (interp.site_easting == null || interp.site_northing == null) return null;
    /* the sounding's own zone, read off its easting as the engine reads it:
     * a survey on the 28N/29N boundary records soundings in both zones, and
     * the project's one zone put the other zone's pegs 660 km away */
    var zone = C.inferZoneForSierraLeone(interp.site_easting);
    var pair = C.utmToGeographic(interp.site_easting, interp.site_northing, zone);
    return { lat: pair.lat, lon: pair.lon };
  }

  function areaWindow(radiusKm) {
    return C.areaWindow(store.get('site') || {}, siteLatLon(),
      radiusKm || store.get('site.mapRadiusKm', 40));
  }

  /* The sentence placing the site: area_map_note, in the engine. */
  function areaNote() {
    return C.areaMapNote(store.get('site') || {}, siteLatLon());
  }

  /* The figures themselves, rasterised for the .docx. `detail` adds the
   * aquifer and geological setting to the locator. */
  async function areaFigures(detail) {
    var geo = mapLayers() || {};
    if (!geo.adminBoundaries) return [];
    var site = store.get('site') || {};
    var latlon = siteLatLon();
    var window_ = areaWindow();
    if (!window_) return [];

    var home = locatorHome(site, latlon);
    var legendItems = [];
    if (latlon) {
      legendItems.push({ label: 'Project site', kind: 'diamond',
        colour: charts.palette().secondary });
    }
    if (home.legend) legendItems.push(home.legend);
    legendItems.push({ label: 'other districts', colour: OTHER_FILL });

    var out = [];
    var locator = charts.siteMap({
      context: (geo.adminBoundaries.features || []),
      contextFill: home.fill,
      highlight: home.highlight, highlightFill: HOME_FILL,
      points: latlon ? [{
        lon: latlon.lon, lat: latlon.lat, label: siteLabel(),
        colour: charts.palette().secondary, size: 6.5,
      }] : [],
      title: 'Location of ' + window_.label,
      legendItems: legendItems,
      credit: 'District boundaries: geoBoundaries (CC BY 4.0).',
      width: 620, height: 560,
    });
    out.push({
      image: await charts.toPng(locator),
      caption: 'Location of ' + window_.label +
        '. Boundaries from geoBoundaries (CC BY 4.0).',
      widthCm: 14,
    });
    if (!detail) return out;

    var pane = { lat: window_.lat, lon: window_.lon, radiusKm: window_.radiusKm };
    if (geo.hydrogeology) {
      out.push({
        image: await charts.toPng(charts.thematicMap({
          features: geo.hydrogeology.features || [],
          context: geo.adminBoundaries.features || [],
          key: 'unit', window: pane,
          points: latlon ? [{ lon: latlon.lon, lat: latlon.lat, label: siteLabel() }] : [],
          title: 'Aquifer productivity around ' + window_.label,
          legendTitle: 'AQUIFER TYPE AND PRODUCTIVITY',
          sourceColours: true,
          credit: 'BGS Africa Groundwater Atlas, CC BY-SA 4.0.',
          sourceScale: charts.bgsSourceScale,
          publisherNote: charts.bgsPublisherNote,
          outline: nationalOutline(geo),
          width: 620, height: 700,
        })),
        caption: 'Aquifer type and productivity around ' + window_.label +
          ', from the BGS Africa Groundwater Atlas country map (CC BY-SA 4.0).',
        widthCm: 14,
      });
    }
    if (geo.geology) {
      out.push({
        image: await charts.toPng(charts.thematicMap({
          features: geo.geology.features || [],
          context: geo.adminBoundaries.features || [],
          key: 'unit', window: pane,
          points: latlon ? [{ lon: latlon.lon, lat: latlon.lat, label: siteLabel() }] : [],
          title: 'Geology around ' + window_.label,
          legendTitle: 'GEOLOGICAL UNIT',
          credit: 'USGS Geologic Map of Africa. Lithology: Geology of ' +
            'Sierra Leone (Fileccia et al. 2017, MoWR/SALWACO, 1:600,000).',
          sourceScale: charts.usgsSourceScale,
          outline: nationalOutline(geo),
          nameLithology: true, district: store.get('site.district') || '',
          width: 620, height: 700,
        })),
        caption: 'Geological setting around ' + window_.label +
          ', from the USGS Geologic Map of Africa (1:5,000,000).',
        widthCm: 14,
      });
    }
    return out;
  }

  /* The same locator, for a document whose subject is an asset rather than
   * the project currently loaded. */
  function siteLikeFromAsset(asset) {
    return {
      community: asset.community || '', chiefdom: asset.chiefdom || '',
      district: asset.district || '', easting: asset.easting,
      northing: asset.northing, utm_zone: asset.utm_zone,
    };
  }

  function areaNoteFor(asset) {
    return withSite(siteLikeFromAsset(asset), areaNote);
  }


  async function areaFiguresFor(asset) {
    return await withSite(siteLikeFromAsset(asset), function () {
      return areaFigures(false);
    });
  }

  /* Run `fn` as though `site` were the loaded project's site, and put the
   * real one back afterwards whatever happens - including when `fn` is async
   * and the substitution has to outlive the call that started it. The
   * locator helpers read the store, which is the right default and the wrong
   * one for an asset drawn from the registry rather than from the open
   * project. */
  async function withSite(site, fn) {
    var previous = store.get('site');
    var merged = Object.assign({}, previous);
    Object.keys(site).forEach(function (key) { merged[key] = site[key]; });
    store.set('site', merged);
    try {
      return await fn();
    } finally {
      store.set('site', previous);
    }
  }

  function districtOf(chiefdom) {
    if (!chiefdom) return '';
    return (C.loadChiefdomDistrict() || {})[chiefdom] || '';
  }

  /* Human-readable coordinates with correct hemisphere letters. Sierra Leone
   * is in the western hemisphere, so longitudes are negative and must read
   * 'W', not 'E'. */
  function fmtLatLon(lat, lon) {
    return C.pyFixed(Math.abs(lat), 4) + ' ' + (lat >= 0 ? 'N' : 'S') + ', ' +
      C.pyFixed(Math.abs(lon), 4) + ' ' + (lon >= 0 ? 'E' : 'W');
  }

  /* The district the sheet states, judged against the district the boundary
   * polygons put the coordinates in: the browser's share of
   * check_site_consistency, which is not otherwise ported here.
   *
   * The stated name is read with the engine's matchDistrict rather than
   * compared as a string, so "Western Area" is the region it names - a site
   * in either of its two districts satisfies it - instead of a mismatch with
   * both of them, and a name that could be two districts is refused and says
   * which two rather than being silently taken for one of them (ROADMAP
   * data-ingestion-5). The sentences are the ones the Python check writes, so
   * a sheet read in the browser and the same sheet read by the toolkit say
   * the same thing about it. */
  function districtNote(site, latlon) {
    var stated = (site && site.district) || '';
    /* a position outside the country is said once, as the Python check says
     * it, and not judged against any district as well */
    if (!stated || !latlon || latlon.outside) return '';
    var matched = C.matchDistrict(stated);
    var resolved = matched[0], candidates = matched[1];
    if (!resolved.length) {
      if (candidates.length > 1) {
        return "District '" + stated + "' could be " + C.orList(candidates) +
          '; it is not read as any of them. Write the district out in full.';
      }
      return "District '" + stated + "' is not a recognised Sierra Leone " +
        'district name, so the coordinates were not checked against it.';
    }
    var where = fmtLatLon(latlon.lat, latlon.lon);
    var found = latlon.chiefdom ? districtOf(latlon.chiefdom) : '';
    if (!found) {
      /* The chiefdom polygons are the only lookup in both engines now: a
       * point no chiefdom holds, and none is within the seam tolerance of,
       * is a point neither engine can place. The Python used to fall back
       * to the pre-2017 district polygons and answer with a district that
       * no longer exists. */
      return 'The boundary polygons place the coordinates (' + where +
        ") in no district, so district '" + stated + "' could not be checked " +
        'against them; the point may be offshore, over the border, or in a ' +
        'gap between the boundaries.';
    }
    if (resolved.indexOf(found) >= 0) return '';
    /* a point just over the drawn line is not a wrong district: the line is
     * only drawn to DISTRICT_EDGE_TOLERANCE_M, and a site on a border can
     * fall either side of it without anybody having written anything wrong */
    if (C.nearDistricts(latlon.lat, latlon.lon, resolved, polygons())) return '';
    return "Stated district '" + stated + "' does not contain the " +
      'coordinates (' + where + '), which fall in ' + latlon.chiefdom +
      ' chiefdom, ' + found + ' district. Verify against the field notes.';
  }

  function chiefdomAt(lat, lon) {
    try {
      return C.chiefdomOfPoint(lat, lon, polygons());
    } catch (e) { return ''; }
  }

  var _polys = null;
  function polygons() {
    /* not kept while empty: the layers may not have arrived yet */
    if (!_polys && C.geoLayers()) _polys = C.loadPolygons();
    return _polys || [];
  }

  /* The bundled map layers, which render() has loaded before drawing any
   * page that reads them; see FIRST_SCREEN. */
  function mapLayers() {
    return C.geoLayers() || {};
  }

  /* WGS84 inverse transverse Mercator, northern hemisphere. */
  /* One implementation of the projection, in the engine, so the map, the
   * report and the coverage join can never place the same borehole in two
   * places. */
  function utmToLatLon(easting, northing, zone) {
    return C.utmToGeographic(easting, northing, zone);
  }

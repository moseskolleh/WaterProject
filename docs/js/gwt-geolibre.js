/* gwt-geolibre.js - the survey as a GeoLibre project file.
 *
 * The port of groundwater/mapping/geolibre.py. Every map this app draws is
 * a picture, which is the right thing to put in a report and the wrong
 * thing to hand to somebody who wants to know what is under the next hill.
 * GeoLibre (https://geolibre.app) is a free, MIT-licensed GIS that runs in
 * a browser, on a desktop, on a phone and inside a notebook, and reads a
 * documented plain-JSON project file. So this writes that file.
 *
 * Nothing is uploaded and nothing is fetched: the project is assembled in
 * the page out of data already here and saved to the machine, which is the
 * same bargain as every other export in this app.
 *
 * Two things about it are deliberate and worth not undoing:
 *
 *   - Layer ids are slugs of their names, not the random UUIDs the format's
 *     own examples use, so the same data writes the same file twice.
 *
 *   - Colours ride on the features as simplestyle properties rather than in
 *     a categorised renderer. The renderer schema is at version 0.1.0 and
 *     will move; simplestyle is older than the format and will outlive this
 *     version of it.
 *
 * One honest difference from the Python side: the bundled boundary, geology
 * and aquifer layers here carry the web app's own copy of those datasets,
 * which is rounded to five decimal places (about a metre) to keep the
 * download down. The package reads the unrounded source. The maps agree;
 * the last decimal place does not, and it does not need to.
 */
(function (global) {
  'use strict';

  var GWT = global.GWT || (global.GWT = {});

  /* The hosted web build. A self-hosted deployment passes its own base. */
  var WEB_APP = 'https://web.geolibre.app/';

  /* The project schema version written here. GeoLibre is young and the
   * format is explicitly pre-1.0, so it is stated rather than assumed. */
  var PROJECT_FORMAT_VERSION = '0.1.0';

  /* A blank background rather than a basemap. Deliberate: this app's own
   * maps are drawn on a plain grid, and a project that silently reached for
   * OpenStreetMap tiles would be its first unannounced network call. */
  var BLANK_BASEMAP = '';

  var COORD_DP = 6;

  /* About 550 m at this latitude. A project holding one borehole has no
   * extent, and framing it literally opens at maximum zoom on a blank
   * background with the wellhead filling the screen. */
  var MIN_SPAN_DEG = 0.005;

  var GRADE_COLORS = {
    'Very good': '#1A9850',
    'Good': '#A6D96A',
    'Moderate': '#FDAE61',
    'Poor': '#D73027',
  };

  /* A water point nobody has reported on is grey, not green. */
  var FUNCTIONAL_COLORS = { yes: '#2E7D5B', no: '#B23A2E', unknown: '#6B7785' };
  var FUNCTIONAL_LABELS = {
    yes: 'Functional', no: 'Non-functional', unknown: 'Unknown',
  };

  /* The same credit strings the package carries. A layer whose licence
   * requires attribution must not be able to leave here without it. */
  var CREDITS = {
    admin: 'Boundaries: geoBoundaries, CC BY 4.0 (predates the 2017 ' +
      'Karene and Falaba districts)',
    geology: 'Geology: USGS Geologic Map of Africa (1:5M), public domain',
    hydro: 'Hydrogeology: BGS Africa Groundwater Atlas (OR/21/063), CC BY-SA 4.0',
    waterPoints: 'Water points: Water Point Data Exchange (WPdx+), CC BY 4.0, ' +
      'https://www.waterpointdata.org',
  };

  var SECRET_HINTS = ['key', 'token', 'secret', 'password', 'credential', 'auth'];

  /* ------------------------------------------------------------- helpers */

  function slug(text) {
    var out = String(text == null ? '' : text).trim().toLowerCase()
      .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
    return out || 'layer';
  }

  /* Round like Python's round(): half to even, so a coordinate written by
   * the package and one written here agree on the ties too. */
  function round6(value) {
    var n = Number(value);
    if (!isFinite(n)) return n;
    var scale = Math.pow(10, COORD_DP);
    var scaled = n * scale;
    var floor = Math.floor(scaled);
    var diff = scaled - floor;
    var rounded;
    if (diff > 0.5) rounded = floor + 1;
    else if (diff < 0.5) rounded = floor;
    else rounded = (floor % 2 === 0) ? floor : floor + 1;
    return rounded / scale;
  }

  function clean(properties) {
    var out = {};
    Object.keys(properties).forEach(function (key) {
      var value = properties[key];
      if (value !== null && value !== undefined && value !== '') out[key] = value;
    });
    return out;
  }

  function feature(geometry, properties) {
    return { type: 'Feature', geometry: geometry, properties: properties };
  }

  function pointFeature(lon, lat, properties) {
    return feature(
      { type: 'Point', coordinates: [round6(lon), round6(lat)] }, properties);
  }

  /* A GeoJSON linear ring, closed. The bundled boundary data does not
   * always close, and GeoJSON requires it. */
  function ring(coords) {
    var out = (coords || []).map(function (pair) {
      return [round6(pair[0]), round6(pair[1])];
    });
    if (out.length >= 2) {
      var first = out[0], last = out[out.length - 1];
      if (first[0] !== last[0] || first[1] !== last[1]) out.push([first[0], first[1]]);
    }
    return out;
  }

  function roundGeometry(geometry) {
    function walk(node) {
      if (node.length === 2 && typeof node[0] === 'number' &&
          typeof node[1] === 'number') {
        return [round6(node[0]), round6(node[1])];
      }
      return node.map(walk);
    }
    if (!geometry || !geometry.coordinates) return geometry;
    return { type: geometry.type, coordinates: walk(geometry.coordinates) };
  }

  /* ------------------------------------------------ features from our data */

  /* Geology and aquifer polygons keep the colour their own dataset assigns,
   * so the project matches the printed map. Serves both layers: the two
   * collections differ only in which property carries the code. */
  function unitFeatures(collection) {
    return ((collection || {}).features || []).map(function (f) {
      var props = f.properties || {};
      return feature(roundGeometry(f.geometry), clean({
        code: props.glg || props.code || '',
        unit: props.unit || '',
        'class': props.era || props.geology || '',
        fill: props.color || '#CCCCCC',
        'fill-opacity': 0.7,
        stroke: '#FFFFFF',
        'stroke-width': 0.5,
      }));
    });
  }

  /* Vertices per protection-zone ring. At 64 the chord across a 3 m circle
   * is under 30 cm, which is finer than the wellhead position is known. */
  var ZONE_SEGMENTS = 64;

  /* The sanitary separation distances, drawn as the rings they are.
   *
   * The table says a latrine must be 20 m away, a burial ground 1000 m, a
   * building 3 m. Those are checked as numbers and reported as numbers,
   * which asks whoever reads it to hold eight radii in their head and
   * compare them against a site they may never have stood on. Drawn on the
   * map over imagery, an encroachment is visible instead of asserted.
   *
   * Each ring is the distance inside which that structure must *not* be:
   * ground the borehole needs kept clear, not ground it occupies.
   *
   * Generated in projected metres and unprojected vertex by vertex, so a
   * 20 m ring is 20 m on the ground. Widest first, so the tight ones stay
   * visible on top of them. */
  function protectionZoneFeatures(lat, lon, distances, zone) {
    var specs = (distances || GWT.data.separationDistances || []).map(function (d) {
      return {
        structure: String(d.structure || ''),
        /* the bundled table carries these as text */
        min_distance_m: Number(d.min_distance_m),
        note: String(d.note || ''),
      };
    }).filter(function (d) { return isFinite(d.min_distance_m); });
    specs.sort(function (a, b) { return b.min_distance_m - a.min_distance_m; });

    var centre = GWT.core.geographicToUtm(lat, lon, zone);
    return specs.map(function (spec) {
      var ring = [];
      for (var step = 0; step < ZONE_SEGMENTS; step++) {
        var angle = 2 * Math.PI * step / ZONE_SEGMENTS;
        var ll = GWT.core.utmToGeographic(
          centre.easting + spec.min_distance_m * Math.cos(angle),
          centre.northing + spec.min_distance_m * Math.sin(angle),
          centre.zone);
        ring.push([round6(ll.lon), round6(ll.lat)]);
      }
      ring.push([ring[0][0], ring[0][1]]);
      return feature({ type: 'Polygon', coordinates: [ring] }, clean({
        structure: spec.structure,
        min_distance_m: spec.min_distance_m,
        note: spec.note,
        meaning: spec.structure + ' must be at least ' + spec.min_distance_m +
          ' m from the borehole; this ring is the ground that has to stay ' +
          'clear of it',
        fill: '#C1772A',
        'fill-opacity': 0.0,
        stroke: '#C1772A',
        'stroke-width': 1.5,
      }));
    });
  }

  /* Administrative polygons, drawn as an outline. Interior rings survive
   * whole: Nongowa encloses Kenema Town, and a chiefdom drawn without its
   * hole swallows the town it surrounds. */
  function areaFeatures(collection) {
    return ((collection || {}).features || []).map(function (f) {
      var props = f.properties || {};
      return feature(roundGeometry(f.geometry), clean({
        name: props.name || '',
        level: props.level || '',
        district: props.district || '',
        fill: '#FFFFFF',
        'fill-opacity': 0.0,
        stroke: '#6B7785',
        'stroke-width': 1,
      }));
    });
  }

  function waterPointFeatures(points) {
    return (points || []).map(function (wp) {
      var key = wp.functional === true ? 'yes'
        : wp.functional === false ? 'no' : 'unknown';
      return pointFeature(wp.lon, wp.lat, clean({
        status: FUNCTIONAL_LABELS[key],
        status_raw: wp.status_text || '',
        source: wp.source || '',
        technology: wp.technology || '',
        improved: wp.improved,
        installed: wp.installed,
        surveyed: wp.report_year,
        months_per_year: wp.months_per_year,
        distance_m: wp.distance_m == null ? null : Math.round(wp.distance_m),
        'marker-color': FUNCTIONAL_COLORS[key],
        fill: FUNCTIONAL_COLORS[key],
        stroke: '#FFFFFF',
      }));
    });
  }

  /* Drill targets, coloured by grade so the ranking reads off the map the
   * way it reads off the table. A score with no position is a table row,
   * not a map feature. */
  function suitabilityFeatures(scores, zone) {
    var out = [];
    (scores || []).forEach(function (score) {
      if (score.easting == null || score.northing == null) return;
      var ll = GWT.core.utmToGeographic(score.easting, score.northing, zone);
      var colour = GRADE_COLORS[score.grade] || '#6B7785';
      out.push(pointFeature(ll.lon, ll.lat, clean({
        sounding: score.sounding_id,
        suitability: Math.round(score.suitability * 10) / 10,
        grade: score.grade,
        rank: score.rank,
        rationale: score.rationale,
        'marker-color': colour,
        fill: colour,
        stroke: '#222222',
      })));
    });
    return out;
  }

  function portfolioFeatures(points) {
    return (points || []).map(function (p) {
      /* portfolioPoints has already classified the free-text status; an
       * unrecognised one is grey, never guessed at. */
      var key = GWT.core.STATUS_COLORS[p.status] ? p.status : 'other';
      var colour = GWT.core.STATUS_COLORS[key];
      return pointFeature(p.lon, p.lat, clean({
        label: p.label,
        status: GWT.core.STATUS_LABELS[key],
        'marker-color': colour,
        fill: colour,
        stroke: '#FFFFFF',
      }));
    });
  }

  /* ------------------------------------------------------ layers and framing */

  function layer(name, features, options) {
    var opts = options || {};
    var kind = opts.kind || 'point';
    var style = {
      simpleStyleEnabled: true,
      fillColor: opts.color || '#17527E',
      strokeColor: opts.stroke || '#FFFFFF',
      strokeWidth: opts.strokeWidth == null ? 1.0 : opts.strokeWidth,
      fillOpacity: kind === 'point' ? 1.0
        : (opts.fillOpacity == null ? 0.7 : opts.fillOpacity),
    };
    if (kind === 'point') style.circleRadius = opts.radius == null ? 7.0 : opts.radius;
    var out = {
      id: slug(name),
      name: name,
      type: 'geojson',
      source: { type: 'geojson' },
      visible: opts.visible === undefined ? true : !!opts.visible,
      opacity: opts.opacity == null ? 1.0 : opts.opacity,
      style: style,
      geojson: { type: 'FeatureCollection', features: features || [] },
      metadata: {},
    };
    if (opts.attribution) out.metadata.attribution = opts.attribution;
    return out;
  }

  function geometryBbox(geometry) {
    var west = Infinity, south = Infinity, east = -Infinity, north = -Infinity;
    function walk(node) {
      if (node.length === 2 && typeof node[0] === 'number' &&
          typeof node[1] === 'number') {
        west = Math.min(west, node[0]); east = Math.max(east, node[0]);
        south = Math.min(south, node[1]); north = Math.max(north, node[1]);
        return;
      }
      node.forEach(walk);
    }
    if (!geometry || !geometry.coordinates) return null;
    walk(geometry.coordinates);
    return west === Infinity ? null : [west, south, east, north];
  }

  function union(boxes) {
    var kept = (boxes || []).filter(Boolean);
    if (!kept.length) return null;
    return [
      Math.min.apply(null, kept.map(function (b) { return b[0]; })),
      Math.min.apply(null, kept.map(function (b) { return b[1]; })),
      Math.max.apply(null, kept.map(function (b) { return b[2]; })),
      Math.max.apply(null, kept.map(function (b) { return b[3]; })),
    ];
  }

  function layerBbox(lyr) {
    return union((((lyr || {}).geojson || {}).features || []).map(function (f) {
      return geometryBbox(f.geometry);
    }));
  }

  function atLeast(bbox, span) {
    var west = bbox[0], south = bbox[1], east = bbox[2], north = bbox[3], mid;
    if (east - west < span) { mid = (west + east) / 2; west = mid - span / 2; east = mid + span / 2; }
    if (north - south < span) { mid = (south + north) / 2; south = mid - span / 2; north = mid + span / 2; }
    return [west, south, east, north];
  }

  function mercY(lat) {
    var clamped = Math.max(Math.min(lat, 85.05112878), -85.05112878);
    return Math.log(Math.tan(Math.PI / 4 + (clamped * Math.PI / 180) / 2));
  }

  /* The format stores a centre and a zoom rather than a bounding box, so
   * the fit is computed here. It is an approximation - the viewport is
   * assumed rather than known - and it is allowed to be. */
  function frame(bbox) {
    var box = atLeast(bbox, MIN_SPAN_DEG);
    var centre = [round6((box[0] + box[2]) / 2), round6((box[1] + box[3]) / 2)];
    var lonSpan = Math.max(box[2] - box[0], 1e-6);
    var ySpan = Math.max(mercY(box[3]) - mercY(box[1]), 1e-9);
    var zoomLon = Math.log2(1024.0 * 360.0 / (256.0 * lonSpan));
    var zoomLat = Math.log2(768.0 * 2 * Math.PI / (256.0 * ySpan));
    var zoom = Math.min(zoomLon, zoomLat) - Math.log2(1 + 2 * 0.12);
    return { center: centre, zoom: Math.round(Math.max(0, Math.min(zoom, 20)) * 100) / 100 };
  }

  /* A square window about a position, in degrees. A degree of latitude is a
   * fixed distance; a degree of longitude shrinks towards the poles. */
  function windowAround(lat, lon, radiusKm) {
    var dlat = radiusKm / 111.32;
    var dlon = radiusKm / Math.max(111.32 * Math.cos(lat * Math.PI / 180), 1e-6);
    return [lon - dlon, lat - dlat, lon + dlon, lat + dlat];
  }

  /* Water points whose position falls inside the window, filtered on the
   * records rather than on features built from them. The coverage page
   * fetches up to 200,000 points into the same place the site page reads
   * them from, and building a quarter of a million features in order to
   * throw almost all of them away is work nobody asked for. */
  function pointsWithinWindow(points, win) {
    if (!win) return (points || []).slice();
    return (points || []).filter(function (p) {
      return p.lon >= win[0] && p.lon <= win[2] &&
        p.lat >= win[1] && p.lat <= win[3];
    });
  }

  /* A bounding-box test, not a clip: a polygon reaching into the window is
   * kept whole, so the unit the site sits in arrives with its real shape
   * and nothing is invented at the edge. */
  function featuresWithin(features, win) {
    if (!win) return (features || []).slice();
    return (features || []).filter(function (f) {
      var b = geometryBbox(f.geometry);
      return b && !(b[2] < win[0] || b[0] > win[2] || b[3] < win[1] || b[1] > win[3]);
    });
  }

  /* A project file is made to be handed to somebody else. The rule this app
   * keeps - the API key stays out of saved project files, so sharing a
   * project never shares the key - is only kept if something checks.
   *
   * It recurses, because a guard that reads only the top level is a guard
   * that says {"service": {"api_key": ...}} is fine, and the file it waves
   * through carries the key anyway. Only the metadata regions are scanned,
   * not feature properties: a credential does not arrive as an attribute of
   * a mapped water point, and walking a national inventory to look for one
   * would cost more than it could ever find. */
  function assertNoSecrets(node, where) {
    var at = where || 'metadata';
    if (Array.isArray(node)) {
      node.forEach(function (item) { assertNoSecrets(item, at); });
      return;
    }
    if (!node || typeof node !== 'object') return;
    Object.keys(node).forEach(function (key) {
      var lowered = String(key).toLowerCase();
      SECRET_HINTS.forEach(function (hint) {
        if (lowered.indexOf(hint) !== -1) {
          throw new Error('refusing to write "' + key + '" into a GeoLibre ' +
            'project (' + at + '): it reads as a credential, and a project ' +
            'file is made to be shared');
        }
      });
      assertNoSecrets(node[key], at + '.' + key);
    });
  }

  /* ------------------------------------------------------------- the project */

  function buildProject(name, layers, options) {
    var opts = options || {};
    var kept = (layers || []).filter(function (l) {
      return l && l.geojson && l.geojson.features && l.geojson.features.length;
    });

    var seen = {};
    kept.forEach(function (l) {
      var base = l.id;
      var count = seen[base] || 0;
      seen[base] = count + 1;
      if (count) l.id = base + '-' + (count + 1);
    });

    /* The survey is what the project is about; the geology underneath it
     * covers Sierra Leone and is context to zoom out to, never the thing to
     * open on. */
    var wanted = (opts.frameOn || []).map(slug);
    var focal = kept.filter(function (l) { return wanted.indexOf(l.id) !== -1; });
    var bbox = union((focal.length ? focal : kept).map(layerBbox));

    var view;
    if (opts.center && opts.zoom != null) {
      view = { center: opts.center, zoom: opts.zoom };
    } else if (!bbox) {
      view = { center: [-11.78, 8.46], zoom: 7.0 };
    } else {
      view = frame(bbox);
    }
    var mapView = {
      center: [round6(view.center[0]), round6(view.center[1])],
      zoom: Math.round(view.zoom * 100) / 100,
      bearing: 0,
      pitch: 0,
    };
    if (bbox) mapView.bbox = atLeast(bbox, MIN_SPAN_DEG).map(round6);

    var metadata = {};
    Object.keys(opts.metadata || {}).forEach(function (k) {
      metadata[k] = opts.metadata[k];
    });
    assertNoSecrets(metadata, 'project metadata');
    kept.forEach(function (l) {
      assertNoSecrets(l.metadata, 'layer "' + l.name + '"');
    });
    if (metadata.generator === undefined) {
      metadata.generator = 'Groundwater Investigation Toolkit';
    }
    var credits = [];
    kept.forEach(function (l) {
      var credit = (l.metadata || {}).attribution;
      if (credit && credits.indexOf(credit) === -1) credits.push(credit);
    });
    if (credits.length) metadata.attribution = credits;

    var styles = {};
    kept.forEach(function (l) { styles[l.id] = l.style; });

    return {
      version: PROJECT_FORMAT_VERSION,
      name: name,
      mapView: mapView,
      basemapStyleUrl: opts.basemap === undefined ? BLANK_BASEMAP : opts.basemap,
      basemapVisible: !!(opts.basemap === undefined ? BLANK_BASEMAP : opts.basemap),
      basemapOpacity: 1,
      layers: kept,
      styles: styles,
      legend: { title: opts.legendTitle || 'Legend', groupByLayer: true },
      metadata: metadata,
    };
  }

  /* Two spaces of indentation and a trailing newline, matching the package,
   * so a project written by either side reads the same in a diff. */
  function stringify(project) {
    return JSON.stringify(project, null, 2) + '\n';
  }

  /* One site, with whatever context the caller has to hand. Every field is
   * optional, because the pages fill up in the order the fieldwork happens.
   * Layers are ordered back to front: geology and aquifers underneath,
   * boundaries over them, then the survey, then the point that matters. */
  function siteProject(options) {
    var opts = options || {};
    var hasFix = opts.lat != null && opts.lon != null;
    var area = opts.area || null;
    var win = null;
    var centre = null;
    var zoom = null;
    if (hasFix) {
      if (opts.windowKm) win = windowAround(opts.lat, opts.lon, opts.windowKm);
    } else if (area) {
      /* A site with no GPS fix still gets a project: the chiefdom it is in,
       * or failing that the district. What it does not get is a marker - a
       * dot at a chiefdom centroid is indistinguishable on screen from a
       * surveyed wellhead, and a reader who cannot tell the difference will
       * measure from it. The area is framed and named; the position stays
       * absent because it is absent.
       *
       * Framed explicitly, because without a fix there is no focal layer
       * for the camera to find and the context layers alone would open on
       * the country. */
      win = windowAround(area.lat, area.lon, area.radiusKm);
      var framed = frame(win);
      centre = framed.center;
      zoom = framed.zoom;
    }
    var layers = [];

    if (opts.hydrogeology) {
      layers.push(layer('Aquifer productivity',
        featuresWithin(unitFeatures(opts.hydrogeology), win),
        { kind: 'polygon', attribution: CREDITS.hydro }));
    }
    if (opts.geology) {
      layers.push(layer('Geology',
        featuresWithin(unitFeatures(opts.geology), win),
        { kind: 'polygon', visible: false, attribution: CREDITS.geology }));
    }
    if (opts.chiefdoms) {
      layers.push(layer('Chiefdoms',
        featuresWithin(areaFeatures(opts.chiefdoms), win),
        { kind: 'polygon', color: '#FFFFFF', stroke: '#6B7785',
          fillOpacity: 0.0, attribution: CREDITS.admin }));
    }
    if (opts.waterPoints) {
      /* Windowed like the context layers, and for a sharper reason: the
       * water points are one of the layers the camera frames on, so a
       * national inventory arriving here would not merely make the file
       * large, it would open the project on Sierra Leone with the survey
       * lost inside it. */
      layers.push(layer('Existing water points',
        waterPointFeatures(pointsWithinWindow(opts.waterPoints, win)),
        { radius: 6.0, attribution: CREDITS.waterPoints }));
    }
    if (opts.suitability) {
      if (opts.zone == null) {
        throw new Error('suitability scores are in projected UTM metres, so a ' +
          'zone is needed to unproject them');
      }
      layers.push(layer('Drill-target suitability',
        suitabilityFeatures(opts.suitability, opts.zone),
        { radius: 9.0, stroke: '#222222' }));
    }
    if (hasFix && opts.protectionZones !== false) {
      layers.push(layer('Sanitary protection zones',
        protectionZoneFeatures(opts.lat, opts.lon, opts.distances, opts.zone),
        { kind: 'polygon', color: '#C1772A', stroke: '#C1772A',
          fillOpacity: 0.0, strokeWidth: 1.5 }));
    }
    if (opts.lat != null && opts.lon != null) {
      layers.push(layer('Site', [pointFeature(opts.lon, opts.lat, clean({
        label: opts.community || 'Site',
        district: opts.district || '',
        chiefdom: opts.chiefdom || '',
        'marker-color': '#B23A2E',
        fill: '#B23A2E',
        stroke: '#FFFFFF',
      }))], { radius: 10.0, color: '#B23A2E' }));
    }

    var metadata = clean({
      community: opts.community || '',
      chiefdom: opts.chiefdom || '',
      district: opts.district || '',
      client: opts.client || '',
      project: opts.project || '',
    });
    if (area && !area.exact) {
      /* Said in the file, not only in the framing: a reader opening this
       * somewhere else has no other way to know the centre is a centroid. */
      metadata.area = area.label;
      metadata.position = 'centred on ' + area.label + ' - an area centroid, ' +
        'not a surveyed position; this site has no GPS fix';
    }
    return buildProject(
      opts.name || opts.community || (area ? area.label : '') || 'Site',
      layers,
      {
        metadata: metadata,
        center: centre,
        zoom: zoom,
        frameOn: ['Site', 'Drill-target suitability', 'Survey points',
          'Existing water points'],
      });
  }

  function portfolioProject(points, options) {
    var opts = options || {};
    var layers = [];
    if (opts.districts) {
      layers.push(layer('Districts', areaFeatures(opts.districts),
        { kind: 'polygon', color: '#FFFFFF', stroke: '#6B7785',
          fillOpacity: 0.0, attribution: CREDITS.admin }));
    }
    layers.push(layer('Boreholes', portfolioFeatures(points), { radius: 8.0 }));
    return buildProject(opts.name || 'Borehole portfolio', layers,
      { frameOn: ['Boreholes'] });
  }

  /* ---------------------------------------------------------------- links */

  /* A published project URL is itself a URL, and the separators that matter
   * - & = ? # - have to be encoded or the outer query swallows the inner
   * one: a signed link ending ?sig=a&expires=1 would otherwise hand
   * GeoLibre an "expires" parameter of its own and truncate the address it
   * was supposed to open. The scheme and path separators stay readable.
   * encodeURIComponent leaves : and / encoded, so they are put back, which
   * makes this exactly the package's quote(value, safe=":/!*'()"). */
  function encodeValue(value) {
    return encodeURIComponent(String(value))
      .replace(/%3A/g, ':').replace(/%2F/g, '/');
  }

  function link(app, params) {
    var query = Object.keys(params).map(function (key) {
      /* a valueless parameter is written bare, as the GeoLibre
       * documentation writes &maponly, rather than as maponly= */
      return params[key] === '' ? key : key + '=' + encodeValue(params[key]);
    }).join('&');
    var base = app.replace(/[?&]+$/, '');
    return query ? base + '?' + query : base;
  }

  /* A link that opens a *published* project. A file that has only been
   * downloaded to this machine has no address, and no query parameter can
   * conjure one - that file is opened from inside GeoLibre instead. */
  function projectLink(url, options) {
    var opts = options || {};
    var params = { url: url };
    if (opts.viewer) params.layout = 'viewer';
    if (opts.theme) params.theme = opts.theme;
    if (opts.maponly) params.maponly = '';
    return link(opts.app || WEB_APP, params);
  }

  function dataLink(url, options) {
    var opts = options || {};
    var params = { data: url };
    if (opts.styleUrl) params.style = opts.styleUrl;
    return link(opts.app || WEB_APP, params);
  }

  /* Gather-and-save, kept here rather than in the page: the page's job is
   * to know where the site, the scores and the water points live, and this
   * module's job is to know what a project file looks like. It also keeps
   * this feature's footprint in gwt-app.js down to the card that offers it.
   *
   * ``input`` is plain data - no store, no DOM - so it is testable from a
   * script with no browser. */
  function saveForSite(input) {
    var project = siteProject(input);
    if (!project.layers.length) return null;
    var stem = String(input.community || 'site').replace(/[^A-Za-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '').toLowerCase() || 'site';
    GWT.support.download(stem + '.geolibre.json', stringify(project),
      'application/geo+json');
    return project;
  }

  GWT.geolibre = {
    WEB_APP: WEB_APP,
    saveForSite: saveForSite,
    PROJECT_FORMAT_VERSION: PROJECT_FORMAT_VERSION,
    CREDITS: CREDITS,
    slug: slug,
    round6: round6,
    ring: ring,
    unitFeatures: unitFeatures,
    areaFeatures: areaFeatures,
    waterPointFeatures: waterPointFeatures,
    suitabilityFeatures: suitabilityFeatures,
    portfolioFeatures: portfolioFeatures,
    protectionZoneFeatures: protectionZoneFeatures,
    layer: layer,
    buildProject: buildProject,
    siteProject: siteProject,
    portfolioProject: portfolioProject,
    stringify: stringify,
    windowAround: windowAround,
    featuresWithin: featuresWithin,
    pointsWithinWindow: pointsWithinWindow,
    projectLink: projectLink,
    dataLink: dataLink,
  };
}(typeof window !== 'undefined' ? window : this));

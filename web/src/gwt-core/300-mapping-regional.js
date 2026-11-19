
  /* ================================================================ regional
   * groundwater/mapping/regional.py and mapping/lithology.py: the area a
   * report maps and what it is called, the district a location map lights,
   * and the ground under a point. gwt-charts.js draws the maps; what they
   * cover and what the report says about them is decided here, where the
   * parity suite can hold it to the Python. The browser used to work these
   * out in the page with rules of its own, and the same site got a different
   * window, a different caveat and a different geology paragraph from each
   * engine.
   */

  /* Which crosswalk region a district belongs to. A coarse USGS class covers
   * different formations in different parts of the country, so a row applies
   * only where its region says it does. _REGIONS in lithology.py. */
  var LITHOLOGY_REGIONS = {
    'Western Area': ['western area', 'western area urban', 'western area rural'],
    'coastal plain': ['bonthe', 'moyamba', 'port loko', 'kambia', 'pujehun'],
    'north and centre': ['bombali', 'tonkolili', 'koinadugu', 'karene', 'falaba'],
  };

  /**
   * @param {string|null} [district]
   * @returns {string}
   */
  function lithologyRegionOf(district) {
    var name = String(district || '').trim().toLowerCase();
    var keys = Object.keys(LITHOLOGY_REGIONS);
    for (var i = 0; i < keys.length; i++) {
      if (LITHOLOGY_REGIONS[keys[i]].indexOf(name) >= 0) return keys[i];
    }
    return 'interior';   /* the default: everything the others do not claim */
  }

  /** What the ground is, for one USGS class in one district - or null, which
   * is the honest answer for a class nobody has annotated and leaves the key
   * showing the source's own wording rather than a guess.
   *
   * This mirrors lithology_for() in the Python engine, including its two
   * refusals: a named district that has no row gets nothing rather than
   * another region's rock, and with no district at all a regional row
   * applies only if every row for the class agrees on the formation.
   * @param {string} glg a USGS class
   * @param {string|null} [district]
   * @returns {Rec|null}
   */
  function lithologyFor(glg, district) {
    var rows = ((GWT.data || {}).lithologyCrosswalk) || [];
    var mine = rows.filter(function (r) { return r.usgs_code === glg; });
    if (!mine.length) return null;
    if (district) {
      var wanted = [lithologyRegionOf(district), 'all'];
      for (var w = 0; w < wanted.length; w++) {
        for (var i = 0; i < mine.length; i++) {
          if (mine[i].region === wanted[w]) return mine[i];
        }
      }
      return null;
    }
    for (var j = 0; j < mine.length; j++) {
      if (mine[j].region === 'all') return mine[j];
    }
    var agreed = mine.map(function (r) {
      return r.formation_name + '\u0000' + r.formation_code;
    });
    var same = agreed.every(function (a) { return a === agreed[0]; });
    return same ? mine[0] : null;
  }

  /** A sentence for a report: the formation, the rock, and what it means.
   * describe() in lithology.py.
   * @param {string} glg a USGS class
   * @param {string|null} [district]
   * @returns {string}
   */
  function describeLithology(glg, district) {
    var row = lithologyFor(glg, district);
    if (!row) return '';
    var text = function (key) { return String(/** @type {Rec} */ (row)[key] || '').trim(); };
    var parts = [text('formation_code')
      ? text('formation_name') + ' (' + text('formation_code').replace(/;/g, ', ') + ')'
      : text('formation_name')];
    if (text('era_actual')) parts.push(text('era_actual'));
    var sentence = parts.join(', ') + '. ' + text('lithology') + '. ' +
      text('aquifer_character') + '.';
    if (text('basis') === 'published') {
      sentence += ' (Formation assignment from the regional literature rather ' +
        'than from a source committed with this toolkit.)';
    }
    return sentence;
  }

  /* The chiefdom polygons, built once: every point placed here goes through
   * them, and 166 polygons would otherwise be rebuilt for each. */
  var regionalPolysCache = null;

  function regionalPolys() {
    /* not cached while empty: the layers may not have arrived yet */
    if (!regionalPolysCache && geoLayers()) regionalPolysCache = loadPolygons();
    return regionalPolysCache || [];
  }

  /** The district a point is in today: district_of in the Python engine.
   *
   * Through the chiefdom first and the crosswalk after it: the bundled
   * district polygons are geoBoundaries as released, which predates the 2017
   * creation of Karene and Falaba, so a point in one of those two has no
   * district polygon to fall in. A point in the seam beside a chiefdom is
   * placed on it, within CHIEFDOM_EDGE_TOLERANCE_M; further out it is off
   * the layer, and "" is the answer (ROADMAP data-ingestion-7).
   * @param {number} lat
   * @param {number} lon
   * @returns {string}
   */
  function districtOfPoint(lat, lon) {
    var crosswalk = loadChiefdomDistrict() || {};
    var polys = regionalPolys();
    for (var i = 0; i < polys.length; i++) {
      if (polyContains(polys[i], lon, lat)) {
        return crosswalk[polys[i].name] || polys[i].district || '';
      }
    }
    var near = nearestChiefdomIndex(lon, lat, outerRingSets(polys));
    if (near === null) return '';
    return crosswalk[polys[near].name] || polys[near].district || '';
  }

  /* The outer ring of each part of a Polygon or MultiPolygon, as the Python
   * loaders keep them in AdminArea.rings and GeologyUnit.ring. */
  function outerRings(geometry) {
    if (!geometry) return [];
    var parts = geometry.type === 'MultiPolygon' ? geometry.coordinates
      : geometry.type === 'Polygon' ? [geometry.coordinates] : [];
    return parts.filter(function (part) { return part && part.length; })
      .map(function (part) { return part[0]; });
  }

  /* Signed area and centroid of a closed ring, by the shoelace formula over
   * consecutive vertices: _ring_area and _ring_centroid. */
  function regionalRingArea(ring) {
    var sum = 0;
    for (var i = 0; i < ring.length - 1; i++) {
      sum += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1];
    }
    return 0.5 * sum;
  }

  function regionalRingCentroid(ring) {
    var area = 0, cx = 0, cy = 0, sx = 0, sy = 0;
    for (var i = 0; i < ring.length - 1; i++) {
      var cross = ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1];
      area += cross;
      cx += (ring[i][0] + ring[i + 1][0]) * cross;
      cy += (ring[i][1] + ring[i + 1][1]) * cross;
    }
    ring.forEach(function (v) { sx += v[0]; sy += v[1]; });
    area /= 2;
    if (Math.abs(area) < 1e-12) return [sx / ring.length, sy / ring.length];
    return [cx / (6 * area), cy / (6 * area)];
  }

  /** Centroid of the largest ring: AdminArea.label_point.
   * @param {number[][][]} rings
   * @returns {number[]}
   */
  function labelPoint(rings) {
    var best = rings[0], bestArea = -1;
    rings.forEach(function (ring) {
      var area = Math.abs(regionalRingArea(ring));
      if (area > bestArea) { bestArea = area; best = ring; }
    });
    return regionalRingCentroid(best);
  }

  /** Half the span of every ring together, in km: _ring_span_km.
   *
   * All the rings, and the span across them. The window used to be sized
   * from the largest ring alone, by its farthest vertex from that ring's
   * centroid, so a chiefdom or district in several parts - Dema, Bonthe - was
   * framed at a different size in each engine, and the scale caveat quoted a
   * different window in each engine's copy of the same report.
   * @param {number[][][]} rings
   * @returns {number}
   */
  function ringSpanKm(rings) {
    var lonMin = Infinity, lonMax = -Infinity, latMin = Infinity, latMax = -Infinity;
    var latSum = 0, count = 0;
    rings.forEach(function (ring) {
      ring.forEach(function (c) {
        if (c[0] < lonMin) lonMin = c[0];
        if (c[0] > lonMax) lonMax = c[0];
        if (c[1] < latMin) latMin = c[1];
        if (c[1] > latMax) latMax = c[1];
        latSum += c[1];
        count += 1;
      });
    });
    var lat = latSum / count;
    var dlat = (latMax - latMin) * 111.32;
    var dlon = (lonMax - lonMin) * 111.32 * Math.cos(lat * Math.PI / 180);
    return Math.max(dlat, dlon) / 2;
  }

  /* The middle of the rings' combined extent, and its half-span in km:
   * _extent_window. */
  function extentWindow(rings) {
    var lonMin = Infinity, lonMax = -Infinity, latMin = Infinity, latMax = -Infinity;
    rings.forEach(function (ring) {
      ring.forEach(function (c) {
        if (c[0] < lonMin) lonMin = c[0];
        if (c[0] > lonMax) lonMax = c[0];
        if (c[1] < latMin) latMin = c[1];
        if (c[1] > latMax) latMax = c[1];
      });
    });
    return [(lonMin + lonMax) / 2, (latMin + latMax) / 2, ringSpanKm(rings)];
  }

  /* Layer name -> full name, for the chiefdoms the layer truncated to
   * fifteen characters ("Bureh Kasseh Ma"). */
  function chiefdomFullNames() {
    var out = {};
    ((GWT.data || {}).chiefdomNames || []).forEach(function (row) {
      out[String(row.layer_name || '').trim()] = String(row.full_name || '').trim();
    });
    return out;
  }

  /** The name a chiefdom is printed under: AdminArea.label.
   * @param {string} layerName
   * @returns {string}
   */
  function chiefdomLabel(layerName) {
    var full = chiefdomFullNames();
    return (own(full, layerName) && full[layerName]) || layerName;
  }

  /** The layer's key for a chiefdom written either way: canonical_chiefdom.
   * An operator typing "Bureh Kasseh Maconteh", the chiefdom's name, got the
   * district window instead of the chiefdom, because the layer only knows
   * "Bureh Kasseh Ma".
   * @param {*} name
   * @returns {string}
   */
  function canonicalChiefdom(name) {
    var written = String(name === null || name === undefined ? '' : name).trim();
    var wanted = written.toLowerCase();
    if (!wanted) return '';
    var full = chiefdomFullNames();
    var keys = Object.keys(full);
    for (var i = 0; i < keys.length; i++) {
      if (wanted === keys[i].toLowerCase() || wanted === full[keys[i]].toLowerCase()) {
        return keys[i];
      }
    }
    return written;
  }

  /* The district polygons of the bundled boundary layer, each with its outer
   * rings: load_admin's districts. */
  function adminDistricts() {
    var features = (((geoLayers() || {}).adminBoundaries || {}).features) || [];
    return features.filter(function (f) {
      return ((f.properties || {}).level || 'ADM2') !== 'ADM0';
    }).map(function (f) {
      return { name: String((f.properties || {}).name || ''), rings: outerRings(f.geometry) };
    });
  }

  /* The rings of every chiefdom the crosswalk puts in a district today:
   * _chiefdom_rings_of. */
  function chiefdomRingsOf(district) {
    var wanted = String(district || '').trim().toLowerCase();
    var crosswalk = loadChiefdomDistrict();
    var rings = [];
    regionalPolys().forEach(function (poly) {
      var current = own(crosswalk, poly.name) ? crosswalk[poly.name] : '';
      if (String(current).trim().toLowerCase() === wanted) {
        poly.rings.forEach(function (ring) { rings.push(ring); });
      }
    });
    return rings;
  }

  /* What a district written on a sheet covers, and what a map calls it:
   * _district_named. Read as the consistency check reads it, so "Port Loko
   * District" is Port Loko and "Western Area" is the region's two districts;
   * compared as typed with the layer's own names, both got no map at all,
   * and the report said no administrative area was recorded right after
   * naming it. A name the matcher cannot resolve is kept as written. */
  function districtNamed(name) {
    var written = String(name === null || name === undefined ? '' : name).trim();
    if (!written) return { label: '', names: [] };
    var resolved = matchDistrict(written)[0];
    return { label: districtLabel(written), names: resolved.length ? resolved : [written] };
  }

  /** The window a local map of this site should cover, if there is one:
   * area_window in the Python engine.
   *
   * A GPS fix gives a point. Without one the recorded chiefdom, or failing
   * that the district, still gives an area, and an area is what most of these
   * maps are asked for: where in the country this is, and what the ground is
   * like around it. Only a site that records neither gets nothing. `latlon`
   * is the site's position as the page reads it, or null.
   * @param {Rec|null} site
   * @param {{lat: number, lon: number}|null} [latlon]
   * @param {number} [radiusKm]
   */
  function areaWindow(site, latlon, radiusKm) {
    if (!site) return null;
    if (latlon) {
      return { lon: latlon.lon, lat: latlon.lat, radiusKm: radiusKm || 40.0,
        label: site.community || 'the site', exact: true };
    }
    var chiefdom = canonicalChiefdom(site.chiefdom).toLowerCase();
    if (chiefdom) {
      var polys = regionalPolys();
      for (var i = 0; i < polys.length; i++) {
        if (polys[i].name.trim().toLowerCase() === chiefdom) {
          var centre = labelPoint(polys[i].rings);
          return { lon: centre[0], lat: centre[1],
            radiusKm: Math.max(ringSpanKm(polys[i].rings) * 1.35, 12.0),
            label: chiefdomLabel(polys[i].name) + ' chiefdom', exact: false };
        }
      }
    }
    var named = districtNamed(site.district);
    if (!named.names.length) return null;
    var byName = {};
    adminDistricts().forEach(function (area) {
      byName[area.name.trim().toLowerCase()] = area;
    });
    if (named.names.length === 1 && own(byName, named.names[0].toLowerCase())) {
      var area = byName[named.names[0].toLowerCase()];
      var point = labelPoint(area.rings);
      return { lon: point[0], lat: point[1],
        radiusKm: Math.max(ringSpanKm(area.rings) * 1.2, 20.0),
        label: named.label, exact: false };
    }
    /* Karene and Falaba postdate the boundary release, so they are assembled
     * from their chiefdoms rather than looked up; a region is its districts
     * together, framed on the middle of the whole as an assembled district
     * is, because no one part of it is the centre. */
    var rings = [];
    named.names.forEach(function (name) {
      var key = name.toLowerCase();
      (own(byName, key) ? byName[key].rings : chiefdomRingsOf(name))
        .forEach(function (ring) { rings.push(ring); });
    });
    if (!rings.length) return null;
    var extent = extentWindow(rings);
    return { lon: extent[0], lat: extent[1],
      radiusKm: Math.max(extent[2] * 1.2, 20.0), label: named.label, exact: false };
  }

  /** Which district a location map lights, and under what name:
   * _home_district in the Python engine. { name, districts, chiefdoms }:
   * the name for the legend, the district polygons to light (lower case, as
   * the layer's names compare), and the chiefdoms to light in their place.
   *
   * The position decides when there is one: "Western Area" written on a
   * sheet resolves to Western Area Rural from the coordinates. Without a
   * position the written name is read as the area window reads it: "Port
   * Loko District" is Port Loko, "Western Area" lights both halves of the
   * peninsula, and Karene or Falaba, which the boundary layer predates, light
   * the chiefdoms the crosswalk assigns to them. The locator used to light a
   * polygon only when its name was typed exactly, so the legend named a
   * district in a colour that appeared nowhere on the map.
   * @param {Rec|null} site
   * @param {{lat: number, lon: number}|null} [latlon]
   */
  function homeDistrict(site, latlon) {
    var none = { name: '', districts: [], chiefdoms: [] };
    if (!site) return none;
    var name = String(site.district || '').trim();
    if (latlon) {
      var found = districtOfPoint(latlon.lat, latlon.lon);
      if (found) name = found;
    }
    if (!name) return none;
    var names = districtNamed(name).names;
    var known = {};
    adminDistricts().forEach(function (area) {
      known[area.name.trim().toLowerCase()] = true;
    });
    var lit = [], missing = [];
    names.forEach(function (n) {
      var key = n.toLowerCase();
      if (own(known, key)) { if (lit.indexOf(key) < 0) lit.push(key); }
      else if (missing.indexOf(key) < 0) missing.push(key);
    });
    var chiefdoms = [];
    if (missing.length) {
      var crosswalk = loadChiefdomDistrict();
      regionalPolys().forEach(function (poly) {
        var current = own(crosswalk, poly.name) ? crosswalk[poly.name] : '';
        if (missing.indexOf(String(current).trim().toLowerCase()) >= 0) {
          chiefdoms.push(poly.name);
        }
      });
    }
    return { name: districtDisplayName(name), districts: lit, chiefdoms: chiefdoms };
  }

  /** One sentence placing the site, for the paragraph above the map:
   * area_map_note in the Python engine. `latlon` is the site's position, or
   * null.
   * @param {Rec|null} site
   * @param {{lat: number, lon: number}|null} [latlon]
   * @returns {string}
   */
  function areaMapNote(site, latlon) {
    if (!site) return 'No site metadata was supplied with this report.';
    /* the district as the area window resolves it: written as typed, a
     * sheet's "Port Loko District" became "Port Loko District district" */
    var where = [site.community, site.chiefdom && site.chiefdom + ' chiefdom',
      site.district && districtLabel(site.district)].filter(Boolean).join(', ');
    if (!latlon) {
      var window_ = areaWindow(site, null);
      if (!window_) {
        return (where ? 'The site is recorded as ' + where + '. ' : '') +
          'Neither a GPS position nor an administrative area is recorded for it, ' +
          'so no map of the area can be drawn. A borehole that cannot be found ' +
          'again on the ground cannot be revisited or maintained: record the ' +
          'position on the field sheet and reissue this report.';
      }
      return (where ? 'The site is recorded as ' + where + '. ' : '') +
        'No GPS position is recorded for it, so the maps below cover ' +
        window_.label + ' rather than the borehole itself and carry no site ' +
        'marker. Record the position on the field sheet and reissue this report: ' +
        'a borehole that cannot be found again on the ground cannot be revisited ' +
        'or maintained.';
    }
    return (where ? 'The site is at ' + where + ', ' : 'The site is at ') +
      pyFixed(Math.abs(latlon.lat), 5) + ' ' + (latlon.lat >= 0 ? 'N' : 'S') + ', ' +
      pyFixed(Math.abs(latlon.lon), 5) + ' ' + (latlon.lon >= 0 ? 'E' : 'W') + '.';
  }

  /** Inside the polygon, and not in a hole that cuts it: _point_in_unit. A
   * hole is ground the unit does not cover - a dyke cutting the country rock,
   * a window of something else - so a point in one is not on this unit,
   * whatever the outer ring says.
   * @param {number} lon
   * @param {number} lat
   * @param {Rec|null} geometry a GeoJSON Polygon or MultiPolygon
   * @returns {boolean}
   */
  function pointInUnit(lon, lat, geometry) {
    if (!geometry) return false;
    var parts = geometry.type === 'MultiPolygon' ? geometry.coordinates
      : geometry.type === 'Polygon' ? [geometry.coordinates] : [];
    return parts.some(function (part) {
      if (!part || !part.length || !pointInRing(lon, lat, part[0])) return false;
      for (var h = 1; h < part.length; h++) {
        if (pointInRing(lon, lat, part[h])) return false;
      }
      return true;
    });
  }

  function unitAt(layer, lat, lon) {
    var features = (layer || {}).features || [];
    for (var i = 0; i < features.length; i++) {
      if (pointInUnit(lon, lat, features[i].geometry)) return features[i];
    }
    return null;
  }

  /** The USGS geology polygon under a point, and the BGS aquifer polygon:
   * geology_unit_at and aquifer_unit_at. Null outside the layer.
   * @param {number} lat
   * @param {number} lon
   * @returns {Rec|null}
   */
  function geologyUnitAt(lat, lon) {
    return unitAt((geoLayers() || {}).geology, lat, lon);
  }

  /**
   * @param {number} lat
   * @param {number} lon
   * @returns {Rec|null}
   */
  function aquiferUnitAt(lat, lon) {
    return unitAt((geoLayers() || {}).hydrogeology, lat, lon);
  }

  /** The district a polygon lies in, for the crosswalk that names it:
   * _unit_district. The crosswalk used to be scoped by the site's district, so
   * the same Freetown Complex polygon was "Freetown Layered Complex" on a
   * Rokel map and "Paleozoic Igneous", the age the crosswalk itself calls
   * wrong, on a Kuntolo map 100 km away. A polygon is where it is.
   * @param {Rec|null} geometry a GeoJSON Polygon or MultiPolygon
   * @returns {string}
   */
  function unitDistrict(geometry) {
    var rings = outerRings(geometry);
    if (!rings.length) return '';
    var ring = rings[0];
    var centre = regionalRingCentroid(ring);
    var found = districtOfPoint(centre[1], centre[0]);
    if (found) return found;
    /* a polygon straddling the border can have its centroid abroad; any
     * vertex inside the country places it */
    var stride = Math.max(1, Math.floor(ring.length / 24));
    for (var i = 0; i < ring.length; i += stride) {
      found = districtOfPoint(ring[i][1], ring[i][0]);
      if (found) return found;
    }
    return '';
  }

  var DEFAULT_GEOLOGY = 'The project area lies within the crystalline ' +
    'basement terrain of Sierra Leone, where groundwater occurs mainly within ' +
    'the weathered overburden (regolith) and in fractured zones of the ' +
    'underlying bedrock. The weathered zone develops on granites, gneisses and ' +
    'related rocks, and its thickness and degree of fracturing control the ' +
    'groundwater potential. Groundwater quality and quantity can be favourable ' +
    'where the borehole position is properly located through appropriate ' +
    'hydrogeological and geophysical investigations.';

  var FREETOWN_GEOLOGY = 'The project area lies within the Freetown Basic ' +
    'Complex. The Freetown Complex is a layered gabbroic anorthosite intrusion ' +
    'emplaced against gneisses and schists of the Kasila Group, and it forms ' +
    'part of the Peninsula and Banana Islands. It is thought to have been ' +
    'formed by multiple injections of magma that occurred intermittently. ' +
    'Groundwater potential within the Freetown Basic Complex is found within ' +
    'weathered and fractured zones of these igneous (crystalline) rocks. ' +
    'Groundwater quality and quantity can be high if the borehole is properly ' +
    'located through appropriate hydrogeological and geophysical investigations.';

  /** The geology paragraph of the geophysical report, from the map under the
   * site: _geology_for in reporting/geophysical.py.
   *
   * With a position it names the USGS unit the site sits on and the BGS
   * aquifer class, through the same crosswalk the map key uses and scoped by
   * where the polygon is, as the key is, so the text and the figures cannot
   * disagree. The browser report said "crystalline basement complex" of every
   * site, the Bullom sands included, beside its own figures showing the
   * Bullom Group and an intergranular aquifer. Without a position the
   * district's region decides.
   * @param {Rec|null} site
   * @param {{lat: number, lon: number}|null} [latlon]
   * @param {string|null} [override] the analyst's own paragraph
   * @returns {string}
   */
  function geologyParagraph(site, latlon, override) {
    if (override) return override;
    var district = (site && site.district) || '';
    if (latlon) {
      var unit = geologyUnitAt(latlon.lat, latlon.lon);
      var aquifer = aquiferUnitAt(latlon.lat, latlon.lon);
      var parts = [];
      if (unit) {
        var props = unit.properties || {};
        var glg = String(props.glg || '');
        var told = describeLithology(glg, unitDistrict(unit.geometry) || district);
        parts.push('The site lies on the unit the USGS Geologic Map of Africa ' +
          'maps as ' + String(props.unit || props.glg || 'unit') + ' (' + glg + '). ' +
          told);
      }
      if (aquifer) {
        var aq = aquifer.properties || {};
        parts.push('The BGS Africa Groundwater Atlas classes the aquifer here as ' +
          String(aq.unit || 'unit') +
          (aq.geology ? ' (' + String(aq.geology).toLowerCase() + ')' : '') + '.');
      }
      if (parts.length) {
        return parts.map(function (p) { return p.trim(); }).join(' ') +
          ' Groundwater potential depends on the thickness of the weathered zone ' +
          'and the degree of fracturing beneath it, which the soundings below ' +
          'resolve.';
      }
    }
    if (lithologyRegionOf(district) === 'Western Area') return FREETOWN_GEOLOGY;
    return DEFAULT_GEOLOGY;
  }

  /* Both bundled unit layers are published at 1:5,000,000. At that scale a
   * 0.5 mm drafting line is 2.5 km on the ground, so below this window the
   * figure says what it is made of. */
  var HONEST_WINDOW_KM = 60;

  /** The note a small window over a small-scale dataset has earned:
   * _scale_caveat, word for word.
   *
   * Empty for a national map, which is the scale the data was published at
   * and needs no apology. `radiusKm` is the half-width of the window that was
   * actually drawn, never the one that was asked for: a national map carrying
   * "4% of this 60 km window" asserts something that is not on it. The window
   * is given to the kilometre: a chiefdom or district window is the area's own
   * size, and "this 43.4293 km window" claimed a precision the sentence is
   * there to disown.
   * @param {number|null|undefined} radiusKm
   * @param {number|null} [sourceScale]
   * @param {string|null} [publisherNote]
   * @returns {string}
   */
  function scaleCaveat(radiusKm, sourceScale, publisherNote) {
    if (radiusKm === null || radiusKm === undefined || !sourceScale ||
        radiusKm > HONEST_WINDOW_KM) return '';
    var lineKm = sourceScale * 0.0005 / 1000;   /* a 0.5 mm line on the sheet */
    var share = lineKm / (2 * radiusKm) * 100;
    var note = 'Drawn from a 1:' + Number(sourceScale).toLocaleString('en-US') +
      ' dataset: a boundary on this map is placed to roughly ' +
      formatG(lineKm) + ' km, which is ' + pyFixed(share, 0) +
      '% of this ' + pyFixed(2 * radiusKm, 0) + ' km window. Read the ' +
      'contacts as regional context, not as mapped ground.';
    return (note + ' ' + (publisherNote || '')).trim();
  }

  /* Sierra Leone in geographic coordinates, with a generous margin: _SL_BOUNDS
   * in ingestion/checks.py, [lonMin, lonMax, latMin, latMax]. */
  var SL_BOUNDS = [-13.6, -10.0, 6.7, 10.2];

  /** The coordinates_outside_country sentence check_site_consistency writes,
   * or '' for a position inside the country. The browser never said it: a
   * degree pair typed without its western sign was drawn in central Africa,
   * off every map, with nothing on the page to say so.
   * @param {number} lat
   * @param {number} lon
   * @returns {string}
   */
  function outsideCountryNote(lat, lon) {
    if (lon >= SL_BOUNDS[0] && lon <= SL_BOUNDS[1] &&
        lat >= SL_BOUNDS[2] && lat <= SL_BOUNDS[3]) return '';
    return 'Coordinates convert to ' + pyFixed(Math.abs(lat), 4) + ' ' +
      (lat >= 0 ? 'N' : 'S') + ', ' + pyFixed(Math.abs(lon), 4) + ' ' +
      (lon >= 0 ? 'E' : 'W') + ' which is outside Sierra Leone; check ' +
      'easting/northing and the UTM zone.';
  }

  /** Whether an easting and northing are small enough to be degrees. No UTM
   * easting lies within 180 m of its zone's origin, 500 km west of the
   * central meridian, and nothing in Sierra Leone is within 90 m of the
   * equator, so a pair that small is a longitude and a latitude typed into
   * the two boxes (geo.utm_boxes_hold_degrees).
   * @param {*} easting
   * @param {*} northing
   * @returns {boolean}
   */
  function utmBoxesHoldDegrees(easting, northing) {
    if (easting === null || northing === null || easting === undefined ||
        northing === undefined || typeof easting === 'boolean' ||
        typeof northing === 'boolean') return false;
    /* a blank box is no number, as Python's float() refuses one, where
     * Number() would read it as 0 */
    if (String(easting).trim() === '' || String(northing).trim() === '') return false;
    var e = Number(easting), n = Number(northing);
    return isFinite(e) && isFinite(n) && Math.abs(e) <= 180 && Math.abs(n) <= 90;
  }

  /* A box's value written out plainly, as Python's _as_typed writes it. */
  function asTyped(value) {
    return pyFixed(Number(value), 10).replace(/0+$/, '').replace(/\.$/, '');
  }

  /** The sentence refusing degrees typed into the UTM boxes, or ''
   * (geo.degrees_in_utm_boxes). The site page read such a pair as degrees
   * and the Python engine as metres near the equator, so one project had a
   * placard this engine certified, an identifier neither could mint and a
   * site the Python engine put outside the country. Neither engine reads a
   * position from them now; the apps offer to convert them, which is the
   * operator saying they are degrees. The position they read as is given,
   * read as readLatLon reads a pasted pair, so an unsigned longitude is west
   * and the sentence says that was assumed.
   * @param {*} easting
   * @param {*} northing
   * @returns {string}
   */
  function degreesInUtmBoxes(easting, northing) {
    if (!utmBoxesHoldDegrees(easting, northing)) return '';
    var eText = asTyped(easting), nText = asTyped(northing);
    var reading = readLatLon(nText + ', ' + eText);
    var ok = reading.lat !== null && reading.lon !== null;
    var position;
    if (ok) {
      var lat = Number(reading.lat), lon = Number(reading.lon);
      position = pyFixed(Math.abs(lat), 5) + '° ' + (lat >= 0 ? 'N' : 'S') + ', ' +
        pyFixed(Math.abs(lon), 5) + '° ' + (lon >= 0 ? 'E' : 'W');
    } else {
      position = String(reading.message).replace(/\.$/, '');
    }
    var text = phrase('site.degrees_in_utm_boxes',
      { easting: eText, northing: nText, position: position });
    return ok && reading.message ? text + ' ' + reading.message : text;
  }

  /** Where a site's recorded position puts it: UTM in the recorded zone or
   * the one the easting implies. {lat, lon, zone}, or null when there is no
   * position or it does not convert. A pair small enough to be degrees typed
   * into the two boxes is no position at all: this used to read it as a
   * latitude and longitude, which the Python engine did not, so the gate
   * passed a placard whose identifier could not be minted.
   * degreesInUtmBoxes says why, and the site page offers to convert it.
   * @param {Rec|null} site
   */
  function sitePosition(site) {
    if (!site) return null;
    var e = site.easting, n = site.northing;
    if (e === null || n === null || e === undefined || n === undefined ||
        e === '' || n === '') return null;
    e = Number(e); n = Number(n);
    if (!isFinite(e) || !isFinite(n)) return null;
    if (utmBoxesHoldDegrees(e, n)) return null;
    var zone = Number(site.utm_zone) || inferZoneForSierraLeone(e);
    var ll = utmToGeographic(e, n, zone);
    if (!ll) return null;
    return { lat: ll.lat, lon: ll.lon, zone: zone };
  }

  Object.assign(C, {
    lithologyRegionOf: lithologyRegionOf, lithologyFor: lithologyFor,
    describeLithology: describeLithology, districtOfPoint: districtOfPoint,
    canonicalChiefdom: canonicalChiefdom, chiefdomLabel: chiefdomLabel,
    ringSpanKm: ringSpanKm, labelPoint: labelPoint,
    areaWindow: areaWindow, homeDistrict: homeDistrict, areaMapNote: areaMapNote,
    pointInUnit: pointInUnit, geologyUnitAt: geologyUnitAt,
    aquiferUnitAt: aquiferUnitAt, unitDistrict: unitDistrict,
    geologyParagraph: geologyParagraph,
    HONEST_WINDOW_KM: HONEST_WINDOW_KM, scaleCaveat: scaleCaveat,
    outsideCountryNote: outsideCountryNote, sitePosition: sitePosition,
    utmBoxesHoldDegrees: utmBoxesHoldDegrees, degreesInUtmBoxes: degreesInUtmBoxes,
  });

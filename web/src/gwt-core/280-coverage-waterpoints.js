
  /* ========================================================= area analysis
   * groundwater/coverage.py and groundwater/waterpoints.py. Where to drill
   * next, and whether a new borehole is the right answer at all.
   */

  var EARTH_RADIUS_M = 6371000.0;
  var DEFAULT_SEARCH_RADIUS_M = 1000.0;
  var SERVICE_RADIUS_M = 500.0;
  var DRILL_NEW = 'drill_new', ASSESS_REHAB = 'assess_rehab', VERIFY_NEED = 'verify_need';

  /* WPdx+ is served from a Socrata endpoint; the resource id is documented but
   * kept overridable so a future dataset id needs no code change. */
  var WPDX_DOMAIN = 'data.waterpointdata.org';
  var WPDX_RESOURCE = 'eqje-vguj';

  var WPDX_CREDIT = 'Water point data: Water Point Data Exchange (WPdx+), ' +
    'CC BY 4.0. Downloaded from wpdx.org.';
  var POPULATION_CREDIT = 'Population: 2015 Population and Housing Census, ' +
    'Statistics Sierra Leone. Boundaries: geoBoundaries, CC BY 4.0.';

  /**
   * @param {number} lat1
   * @param {number} lon1
   * @param {number} lat2
   * @param {number} lon2
   * @returns {number}
   */
  function haversineM(lat1, lon1, lat2, lon2) {
    var rad = Math.PI / 180;
    var p1 = lat1 * rad, p2 = lat2 * rad;
    var dphi = (lat2 - lat1) * rad, dlam = (lon2 - lon1) * rad;
    var a = Math.sin(dphi / 2) * Math.sin(dphi / 2) +
      Math.cos(p1) * Math.cos(p2) * Math.sin(dlam / 2) * Math.sin(dlam / 2);
    return 2 * EARTH_RADIUS_M * Math.asin(Math.sqrt(a));
  }

  /** Ray casting on a closed ring.
   * @param {number} lon
   * @param {number} lat
   * @param {number[][]} ring
   * @returns {boolean}
   */
  function pointInRing(lon, lat, ring) {
    var inside = false;
    for (var i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      var xi = ring[i][0], yi = ring[i][1], xj = ring[j][0], yj = ring[j][1];
      if (((yi > lat) !== (yj > lat)) &&
          (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi)) {
        inside = !inside;
      }
    }
    return inside;
  }

  /* The bundled map layers, GWT.data.geo. They are a script of their own,
   * gwt-geo.js, fetched the first time a view needs a map, because they are
   * most of the app's data by weight and the first screen uses none of them.
   * The engine worker imports them here, the first time a task reads them.
   * The page loads them before it draws a view that needs them; asked for
   * them before that, it says so loudly rather than answer that a point is
   * in no district, which is the answer an empty layer gives. */
  var geoMissingSaid = false;
  function geoLayers() {
    var data = GWT.data || {};
    if (!data.geo && typeof GWT.loadNow === 'function') GWT.loadNow('geo');
    if (!data.geo && !geoMissingSaid && typeof GWT.load === 'function') {
      geoMissingSaid = true;
      console.error('The map layers were read before gwt-geo.js was loaded; ' +
        'call GWT.load(\'geo\') first.');
    }
    return data.geo || null;
  }

  /** Chiefdom polygons, with bounding boxes so the point-in-polygon scan over
   * 166 chiefdoms stays cheap for a few thousand water points.
   * @param {Rec|null} [layer] a GeoJSON FeatureCollection; the bundled chiefdoms when not given
   * @returns {Rec[]}
   */
  function loadPolygons(layer) {
    var source = layer || (geoLayers() || {}).chiefdomBoundaries;
    if (!source) return [];
    return (source.features || []).map(function (feature) {
      var geometry = feature.geometry || {};
      var parts = geometry.type === 'MultiPolygon'
        ? geometry.coordinates : [geometry.coordinates || []];
      var rings = [], holes = [], bboxes = [];
      parts.forEach(function (part) {
        if (!part || !part.length) return;
        var outer = part[0];
        rings.push(outer);
        holes.push(part.slice(1));
        var lons = outer.map(function (c) { return c[0]; });
        var lats = outer.map(function (c) { return c[1]; });
        bboxes.push([arrMin(lons), arrMin(lats), arrMax(lons), arrMax(lats)]);
      });
      return {
        name: (feature.properties || {}).name || '',
        district: (feature.properties || {}).district || '',
        rings: rings, holes: holes, bboxes: bboxes, feature: feature,
      };
    }).filter(function (p) { return p.rings.length; });
  }

  /**
   * @param {Polygon} poly
   * @param {number} lon
   * @param {number} lat
   * @returns {boolean}
   */
  function polyContains(poly, lon, lat) {
    for (var i = 0; i < poly.rings.length; i++) {
      var b = poly.bboxes[i];
      if (lon < b[0] || lon > b[2] || lat < b[1] || lat > b[3]) continue;
      if (!pointInRing(lon, lat, poly.rings[i])) continue;
      var inHole = (poly.holes[i] || []).some(function (hole) {
        return pointInRing(lon, lat, hole);
      });
      if (!inHole) return true;
    }
    return false;
  }

  /* How far outside every chiefdom a point may fall and still be placed on the
   * chiefdom whose ring it is nearest to, in metres.
   *
   * Each ring of the bundled layer was simplified on its own, so two rings
   * that were once one shared border no longer meet exactly, and the thin
   * slivers between them - about 37 km2 of ground nationally - are inside no
   * chiefdom at all (ROADMAP data-ingestion-7). A point in one of those seams
   * is metres from the border it belongs on, and which side of that border it
   * fell on is below the resolution of the layer, so it is resolved to the
   * nearest ring. Nearly every seam in the bundled layer is far narrower than
   * this; the few places that are wider are where three chiefdoms meet, and a
   * point there is left unplaced rather than given one of the three.
   *
   * The number is metres and not kilometres on purpose. Beyond it a point is
   * not on a border at all but in a real hole in the layer - the Maforki wedge
   * withheld pending review is 20 km2 of such ground - and there every lookup
   * answers with nothing rather than with the name of whatever lies nearest,
   * because an unplaced point is a flag on a report while a placed one is a
   * district on a document somebody signs. The same number as
   * coverage.CHIEFDOM_EDGE_TOLERANCE_M, so the two engines snap at one
   * distance and not at two. */
  var CHIEFDOM_EDGE_TOLERANCE_M = 50.0;

  /* Metres per degree of latitude, and per degree of longitude at the equator
   * (shrunk by the cosine of the latitude where it is used). What they convert
   * is a few tens of metres between a point and a ring it is all but touching,
   * so the local flat-earth distance below is ample and a projection would be
   * false precision. */
  var M_PER_DEG_LAT = 110600.0;
  var M_PER_DEG_LON = 111320.0;

  /** Metres from a point to the nearest segment of a ring.
   *
   * Distance to the ring as a line, not to its vertices: a simplified ring can
   * run hundreds of metres between two vertices, and a point in the seam
   * beside that stretch is metres from the border and far from either end of
   * it. haversineM is point to point and cannot answer this.
   * @param {number} lon
   * @param {number} lat
   * @param {number[][]} ring
   * @returns {number}
   */
  function ringDistanceM(lon, lat, ring) {
    var scale = M_PER_DEG_LON * Math.cos(lat * Math.PI / 180);
    var best = Infinity;
    for (var i = 0; i < ring.length - 1; i++) {
      var ax = (ring[i][0] - lon) * scale;
      var ay = (ring[i][1] - lat) * M_PER_DEG_LAT;
      var dx = (ring[i + 1][0] - lon) * scale - ax;
      var dy = (ring[i + 1][1] - lat) * M_PER_DEG_LAT - ay;
      var length2 = dx * dx + dy * dy;
      /* where on the segment the perpendicular falls, clamped to its ends; a
       * segment of zero length (a vertex repeated by the simplification) would
       * divide by zero, and its own end point is the answer there. */
      var t = 0;
      if (length2 > 0) {
        t = -(ax * dx + ay * dy) / length2;
        if (t < 0) t = 0; else if (t > 1) t = 1;
      }
      var px = ax + t * dx, py = ay + t * dy;
      var metres = Math.sqrt(px * px + py * py);
      if (metres < best) best = metres;
    }
    return best;
  }

  /** Which of the areas a point in none of them is nearest to, if any is near.
   *
   * ringSets is each area's outer rings, in the layer's own order. Returns the
   * index of the area whose ring is nearest, when that ring is closer than
   * toleranceM, and null when nothing is that close - the point is then in no
   * chiefdom and is left in none.
   *
   * Ties go to the earlier area, which is the rule the containment walk
   * already follows. Interior rings are not candidates: a point in the seam
   * between an enclave and the chiefdom around it (Kenema Town inside Nongowa)
   * belongs to the enclave it is touching, not to the hole it fell in.
   * coverage.nearest_chiefdom_index.
   * @param {number} lon
   * @param {number} lat
   * @param {number[][][][]} ringSets each area's outer rings
   * @param {number} [toleranceM]
   * @returns {number|null}
   */
  function nearestChiefdomIndex(lon, lat, ringSets, toleranceM) {
    var tolerance = toleranceM === undefined ? CHIEFDOM_EDGE_TOLERANCE_M : toleranceM;
    /* the ring's bounding box grown by the tolerance: a point outside that box
     * is further than the tolerance from every point of the ring, so the
     * distance need not be computed at all. A national water-point pull asks
     * this of every point it could not place. */
    var dLat = tolerance / M_PER_DEG_LAT;
    var dLon = tolerance /
      (M_PER_DEG_LON * Math.max(Math.cos(lat * Math.PI / 180), 1e-6));
    var bestIndex = null, bestM = tolerance;
    for (var i = 0; i < ringSets.length; i++) {
      var rings = ringSets[i] || [];
      for (var j = 0; j < rings.length; j++) {
        var ring = rings[j];
        if (!ring || ring.length < 2) continue;  // a replacement layer can carry a degenerate ring
        var minLon = Infinity, maxLon = -Infinity;
        var minLat = Infinity, maxLat = -Infinity;
        for (var k = 0; k < ring.length; k++) {
          if (ring[k][0] < minLon) minLon = ring[k][0];
          if (ring[k][0] > maxLon) maxLon = ring[k][0];
          if (ring[k][1] < minLat) minLat = ring[k][1];
          if (ring[k][1] > maxLat) maxLat = ring[k][1];
        }
        if (lon < minLon - dLon || lon > maxLon + dLon ||
            lat < minLat - dLat || lat > maxLat + dLat) continue;
        var metres = ringDistanceM(lon, lat, ring);
        if (metres < bestM) { bestIndex = i; bestM = metres; }
      }
    }
    return bestIndex;
  }

  /** The outer rings of each polygon, in the layer's order, as
   * nearestChiefdomIndex takes them.
   * @param {Polygon[]} polys
   * @returns {number[][][][]}
   */
  function outerRingSets(polys) {
    return polys.map(function (poly) { return poly.rings; });
  }

  /** The chiefdom polygon holding a point, or "" when no chiefdom is near it.
   *
   * A point no polygon contains is placed on the chiefdom whose ring is
   * nearest, when that ring is within CHIEFDOM_EDGE_TOLERANCE_M - the seams
   * the independently simplified rings leave along their shared borders are
   * that wide, and a point in one is on the border rather than outside the
   * country. Further out than that it stays unplaced, because the ground the
   * layer does not carry - the withheld Maforki wedge in Kono is 20 km2 of it
   * - is ground this toolkit cannot place, and saying so is the honest answer
   * (ROADMAP data-ingestion-7).
   *
   * Every count and grouping below goes through this one function, so the
   * browser closes a seam at one distance and in one place, as the Python
   * does.
   * @param {number} lat
   * @param {number} lon
   * @param {Polygon[]} polys
   * @returns {string}
   */
  function chiefdomOfPoint(lat, lon, polys) {
    for (var i = 0; i < polys.length; i++) {
      if (polyContains(polys[i], lon, lat)) return polys[i].name;
    }
    var near = nearestChiefdomIndex(lon, lat, outerRingSets(polys));
    return near === null ? '' : polys[near].name;
  }

  /* How far outside a stated district's drawn boundary a point may fall and
   * still not be reported as a conflict with it, in metres.
   *
   * The chiefdom rings are simplified with Douglas-Peucker at 0.0008 degrees,
   * so every boundary the district check judges by is drawn to within about
   * 89 m of the line it came from. A site 40 m over the drawn line can be on
   * either side of the real one, and a sheet naming the neighbouring district
   * there has not been shown to be wrong. The tolerance is that drawing error
   * and no more: the 5.5 km of slack the bounding boxes allowed is what let
   * one wrong-district statement in fourteen through them. The same number as
   * ingestion.checks.DISTRICT_EDGE_TOLERANCE_M. */
  var DISTRICT_EDGE_TOLERANCE_M = 90.0;

  /** Whether a point is inside, or within toleranceM of, these districts.
   *
   * A district is the chiefdoms the crosswalk puts in it today, the same
   * rings chiefdomOfPoint places a point by, and the distance is to the ring
   * as a line. Containment is asked as well as distance because the rings
   * were simplified one at a time and can overlap along a shared border: a
   * point in the overlap is inside both districts as drawn, even though
   * chiefdomOfPoint can only return the first. mapping.regional.near_districts.
   * @param {number} lat
   * @param {number} lon
   * @param {string[]} districts
   * @param {Polygon[]} polys
   * @param {number} [toleranceM]
   * @returns {boolean}
   */
  function nearDistricts(lat, lon, districts, polys, toleranceM) {
    var tolerance = toleranceM === undefined ? DISTRICT_EDGE_TOLERANCE_M : toleranceM;
    var crosswalk = loadChiefdomDistrict();
    var rings = [];
    for (var i = 0; i < polys.length; i++) {
      var poly = polys[i];
      if (districts.indexOf(crosswalk[poly.name] || poly.district) < 0) continue;
      if (polyContains(poly, lon, lat)) return true;
      rings = rings.concat(poly.rings);
    }
    return nearestChiefdomIndex(lon, lat, [rings], tolerance) !== null;
  }

  /**
   * @param {Rec[]|null} [rows] the bundled table when not given
   * @returns {Record<string, number>}
   */
  function loadDistrictPopulation(rows) {
    var source = rows || (GWT.data && GWT.data.populationDistrict) || [];
    /** @type {Record<string, number>} */
    var out = {};
    source.forEach(function (row) {
      out[String(row.district).trim()] = Number(row.population);
    });
    return out;
  }

  /** The fixed scale the coverage map is coloured by, the same table the
   * Python engine reads. Colouring by a scale recomputed from each map made
   * two maps of one country incomparable.
   * @param {Rec[]|null} [rows] the bundled table when not given
   */
  function loadServiceClasses(rows) {
    var source = rows || (GWT.data && GWT.data.coverageServiceClasses) || [];
    return source.map(function (row) {
      var top = String(row.max_people_per_point === null ||
        row.max_people_per_point === undefined ? '' : row.max_people_per_point).trim();
      return {
        kind: String(row.kind || 'class').trim(),
        max_people_per_point: top === '' ? null : Number(top),
        label: String(row.label || '').trim(),
        basis: String(row.basis || '').trim(),
        colour: String(row.colour || '').trim(),
      };
    });
  }

  /**
   * @param {Rec[]|null} [rows] the bundled crosswalk when not given
   * @returns {Record<string, string>}
   */
  function loadChiefdomDistrict(rows) {
    var source = rows || (GWT.data && GWT.data.chiefdomDistrict) || [];
    /** @type {Record<string, string>} */
    var out = {};
    source.forEach(function (row) {
      out[String(row.chiefdom).trim()] = String(row.district).trim();
    });
    return out;
  }

  /* --- reading a district name off a sheet ---------------------------------
   *
   * groundwater/ingestion/checks.py. The browser has no port of
   * check_site_consistency; what it has is the site page's callout comparing
   * the district on the sheet against the district the chiefdom polygons put
   * the coordinates in. Reading the name is the part both engines must agree
   * on, and it used to be a substring test in each of them.
   */

  /* "Western Area" is a region, not one of the sixteen districts: it is the
   * peninsula's two districts together. Field sheets write it constantly, so
   * it is read as both of them - a site anywhere in either satisfies it -
   * rather than as Western Area Urban, which is what taking the first
   * substring hit did, flagging every correctly labelled site on the
   * southern peninsula (ROADMAP data-ingestion-5). */
  var DISTRICT_REGIONS = {
    'western area': ['Western Area Urban', 'Western Area Rural'],
  };

  /* The sixteen districts, spelled as the boundary lookups spell them: taken
   * from the chiefdom -> current-district crosswalk rather than from a list
   * written out here, so the names this reading accepts are exactly the names
   * the point lookup can return. */
  function districtNames() {
    var crosswalk = loadChiefdomDistrict(), seen = {}, out = [];
    Object.keys(crosswalk).forEach(function (chiefdom) {
      var district = crosswalk[chiefdom];
      if (district && !own(seen, district)) {
        seen[district] = true;
        out.push(district);
      }
    });
    return out.sort();
  }

  /* A stated name reduced to what can be compared: case, spacing, and a
   * trailing "district" the sheet added ("Port Loko District"). */
  function districtKey(name) {
    var words = String(name === null || name === undefined ? '' : name)
      .replace(/\./g, ' ').split(/\s+/).filter(Boolean);
    if (words.length > 1) {
      var last = words[words.length - 1].toLowerCase().replace(/,+$/, '');
      if (last === 'district' || last === 'districts') {
        words = words.slice(0, words.length - 1);
      }
    }
    return words.join(' ').toLowerCase();
  }

  /* Every administrative name read here -> the districts it covers. */
  function namedAreas() {
    var areas = {};
    districtNames().forEach(function (name) { areas[districtKey(name)] = [name]; });
    Object.keys(DISTRICT_REGIONS).forEach(function (key) {
      areas[key] = DISTRICT_REGIONS[key].slice();
    });
    return areas;
  }

  function districtPrefixHit(key, candidate) {
    return candidate.indexOf(key) === 0;
  }

  /* True when every word of the stated name begins a word of the candidate,
   * in order: "Western Urban" for Western Area Urban. Each word is consumed
   * as it is matched, so one candidate word cannot answer for two. */
  function districtWordsHit(key, candidate) {
    var words = candidate.split(' '), parts = key.split(' '), index = 0;
    for (var p = 0; p < parts.length; p++) {
      var hit = false;
      while (index < words.length) {
        var word = words[index];
        index += 1;
        if (word.indexOf(parts[p]) === 0) { hit = true; break; }
      }
      if (!hit) return false;
    }
    return true;
  }

  function sameDistrictSet(a, b) {
    return a.slice().sort().join('|') === b.slice().sort().join('|');
  }

  /** Read a district name off a sheet: [resolved, candidates].
   *
   * resolved is the districts the name can only mean - one district, or the
   * two of the Western Area for a name that means the region. It is empty
   * when the name matches nothing, and empty when it matches more than one
   * district, in which case candidates lists what it could have meant. An
   * exact name wins; then a name that prefixes exactly one ("Bomb" for
   * Bombali); then one whose words begin the words of exactly one ("Western
   * Urban"). Matching on the first substring hit, which is what this did,
   * read "Ko" as Port Loko and "Western Area" as Western Area Urban; a name
   * that could be two districts is worth refusing, and saying which two,
   * rather than silently picking one of them.
   * @param {*} name
   * @returns {[string[], string[]]}
   */
  function matchDistrict(name) {
    var key = districtKey(name);
    if (!key) return [[], []];
    var areas = namedAreas();
    if (own(areas, key)) return [areas[key].slice(), areas[key].slice()];
    var tiers = [districtPrefixHit, districtWordsHit];
    for (var t = 0; t < tiers.length; t++) {
      var names = Object.keys(areas).filter(function (known) {
        return tiers[t](key, known);
      });
      if (!names.length) continue;
      var covered = [], seen = {};
      names.forEach(function (known) {
        areas[known].forEach(function (district) {
          if (!own(seen, district)) { seen[district] = true; covered.push(district); }
        });
      });
      covered.sort();
      for (var i = 0; i < names.length; i++) {
        /* "Western" matches both halves of the Western Area and the region
         * over them, and the region is a single answer; "Ko" matches
         * Koinadugu and Kono, and there is no such answer. */
        if (sameDistrictSet(areas[names[i]], covered)) {
          return [areas[names[i]].slice(), areas[names[i]].slice()];
        }
      }
      return [[], covered];
    }
    return [[], []];
  }

  /** The districts a district name written on a sheet can only mean.
   * @param {*} name
   * @returns {string[]}
   */
  function districtsNamed(name) {
    return matchDistrict(name)[0];
  }

  /** The name a district written on a sheet is printed under: the district it
   * resolves to - "Port Loko" for "Port Loko District" - or the region's own
   * name for a name that means a region, and the sheet's words as written for
   * a name that resolves to nothing. Printed as typed, the name went into
   * client documents as "Port Loko District district". district_display_name
   * in the Python engine.
   * @param {*} name
   * @returns {string}
   */
  function districtDisplayName(name) {
    var resolved = matchDistrict(name)[0];
    if (resolved.length === 1) return resolved[0];
    var keys = Object.keys(DISTRICT_REGIONS);
    for (var i = 0; i < keys.length; i++) {
      if (resolved.length && sameDistrictSet(DISTRICT_REGIONS[keys[i]], resolved)) {
        /* the keys are written in lower case to be compared, and the
         * region's name is those words capitalised, as str.title() does */
        return keys[i].replace(/\b[a-z]/g, function (c) { return c.toUpperCase(); });
      }
    }
    return String(name === null || name === undefined ? '' : name).trim();
  }

  /** How a report names the district a sheet states: "Port Loko district". A
   * region is not a district, so "Western Area" is printed as itself rather
   * than as "Western Area district". district_label in the Python engine.
   * @param {*} name
   * @returns {string}
   */
  function districtLabel(name) {
    var shown = districtDisplayName(name);
    if (!shown) return '';
    if (matchDistrict(name)[0].length > 1) return shown;
    return shown + ' district';
  }

  /** A list an operator reads as a sentence: "Koinadugu or Kono".
   * @param {string[]|null} [names]
   * @returns {string}
   */
  function orList(names) {
    var list = (names || []).slice();
    if (list.length < 2) return list.join('');
    return list.slice(0, list.length - 1).join(', ') + ' or ' + list[list.length - 1];
  }

  /** Population per chiefdom polygon, aggregated from the census through the
   * crosswalk. District totals are conserved exactly by construction, and the
   * member list drives the reconciliation panel that shows how post-2017
   * chiefdoms fold into the pre-2017 polygons.
   * @param {Rec[]|null} [censusRows]
   * @param {Rec[]|null} [crosswalkRows]
   */
  function chiefdomPopulation(censusRows, crosswalkRows) {
    var census = censusRows || (GWT.data && GWT.data.populationChiefdom) || [];
    var crossSource = crosswalkRows || (GWT.data && GWT.data.censusCrosswalk) || [];
    var crosswalk = {};
    crossSource.forEach(function (row) {
      crosswalk[String(row.district).trim() + '||' + String(row.census_chiefdom).trim()] =
        String(row.gb_chiefdom).trim();
    });
    var population = {}, members = {}, missing = [];
    census.forEach(function (row) {
      var key = String(row.district).trim() + '||' + String(row.chiefdom).trim();
      var gb = crosswalk[key];
      if (gb === undefined) { missing.push(key); return; }
      population[gb] = (population[gb] || 0) + Number(row.population);
      (members[gb] = members[gb] || []).push(String(row.chiefdom).trim());
    });
    if (missing.length) {
      throw new Error(missing.length + ' census chiefdom(s) have no crosswalk ' +
        'row, e.g. ' + missing[0].replace('||', ' / ') +
        '; check data/sl_census_crosswalk.csv');
    }
    return { population: population, members: members };
  }

  /**
   * @param {WaterPoint[]} points
   * @param {Polygon[]} polys
   */
  function countPointsByChiefdom(points, polys) {
    var counts = {}, unassigned = [];
    points.forEach(function (wp) {
      var chiefdom = chiefdomOfPoint(wp.lat, wp.lon, polys);
      if (!chiefdom) { unassigned.push(wp); return; }
      var bucket = counts[chiefdom] || (counts[chiefdom] = { total: 0, functional: 0 });
      bucket.total += 1;
      if (wp.functional === true) bucket.functional += 1;
    });
    return { counts: counts, unassigned: unassigned };
  }

  /**
   * @param {WaterPoint[]} points
   * @param {Polygon[]} polys
   * @param {Record<string, string>} chiefdomDistrict
   */
  function countPointsByDistrict(points, polys, chiefdomDistrict) {
    var counts = {}, unassigned = [];
    points.forEach(function (wp) {
      var chiefdom = chiefdomOfPoint(wp.lat, wp.lon, polys);
      var district = chiefdom ? chiefdomDistrict[chiefdom] : '';
      if (!district) { unassigned.push(wp); return; }
      var bucket = counts[district] || (counts[district] = { total: 0, functional: 0 });
      bucket.total += 1;
      if (wp.functional === true) bucket.functional += 1;
    });
    return { counts: counts, unassigned: unassigned };
  }

  /** The points themselves rather than a tally: the counts are enough to
   * divide a population by, but not enough to say when they were surveyed or
   * whether they last the dry season.
   * @param {WaterPoint[]} points
   * @param {Polygon[]} polys
   * @param {Record<string, string>} chiefdomDistrict
   */
  function groupPointsByDistrict(points, polys, chiefdomDistrict) {
    var grouped = {}, unassigned = [];
    points.forEach(function (wp) {
      var chiefdom = chiefdomOfPoint(wp.lat, wp.lon, polys);
      var district = chiefdom ? chiefdomDistrict[chiefdom] : '';
      if (!district) { unassigned.push(wp); return; }
      (grouped[district] || (grouped[district] = [])).push(wp);
    });
    return { grouped: grouped, unassigned: unassigned };
  }

  /**
   * @param {WaterPoint[]} points
   * @param {Polygon[]} polys
   */
  function groupPointsByChiefdom(points, polys) {
    var grouped = {}, unassigned = [];
    points.forEach(function (wp) {
      var chiefdom = chiefdomOfPoint(wp.lat, wp.lon, polys);
      if (!chiefdom) { unassigned.push(wp); return; }
      (grouped[chiefdom] || (grouped[chiefdom] = [])).push(wp);
    });
    return { grouped: grouped, unassigned: unassigned };
  }

  /* Ranking is worst-first: areas with no functional source mapped rank at the
   * very top - unmet need is effectively infinite there - then the rest by
   * descending people-per-functional-point, with population breaking ties. */
  function rankCoverage(rows) {
    rows.sort(function (a, b) {
      var ka = a.people_per_point !== null ? 1 : 0;
      var kb = b.people_per_point !== null ? 1 : 0;
      if (ka !== kb) return ka - kb;
      var pa = a.people_per_point || 0, pb = b.people_per_point || 0;
      if (pa !== pb) return pb - pa;
      return b.population - a.population;
    });
    rows.forEach(function (row, i) { row.rank = i + 1; });
    return rows;
  }

  /**
   * @param {Record<string, number>} population
   * @param {Record<string, {total: number, functional: number}>} counts
   */
  function coverageRows(population, counts) {
    var rows = Object.keys(population).map(function (name) {
      var bucket = counts[name] || { total: 0, functional: 0 };
      return {
        name: name, district: name, population: population[name],
        water_points: bucket.total, functional_points: bucket.functional,
        people_per_point: bucket.functional > 0
          ? population[name] / bucket.functional : null,
        rank: 0,
      };
    });
    return rankCoverage(rows);
  }

  /**
   * @param {Record<string, number>} population
   * @param {Record<string, {total: number, functional: number}>} counts
   * @param {Record<string, string>} chiefdomDistrict
   */
  function chiefdomCoverageRows(population, counts, chiefdomDistrict) {
    var rows = Object.keys(population).map(function (name) {
      var bucket = counts[name] || { total: 0, functional: 0 };
      return {
        name: name, chiefdom: name, district: chiefdomDistrict[name] || '',
        population: population[name], water_points: bucket.total,
        functional_points: bucket.functional,
        people_per_point: bucket.functional > 0
          ? population[name] / bucket.functional : null,
        rank: 0,
      };
    });
    return rankCoverage(rows);
  }

  /** worst_served_* is the highest FINITE people-per-point, reported separately
   * from the ranking because areas with no functional source have an undefined
   * ratio, sort to rank 1 and are counted by n_no_source instead.
   * @param {Rec[]} rows what coverageRows returns
   */
  function coverageStats(rows) {
    var served = rows.filter(function (r) { return r.people_per_point !== null; });
    var worstServed = served.reduce(function (a, b) {
      return (!a || b.people_per_point > a.people_per_point) ? b : a;
    }, /** @type {Rec|null} */ (null));
    var totalPop = rows.reduce(function (a, r) { return a + r.population; }, 0);
    var totalFunctional = rows.reduce(function (a, r) { return a + r.functional_points; }, 0);
    return {
      n_areas: rows.length,
      worst_area: rows.length ? rows[0].name : null,
      worst_people_per_point: rows.length ? rows[0].people_per_point : null,
      worst_served_area: worstServed ? worstServed.name : null,
      worst_served_people_per_point: worstServed ? worstServed.people_per_point : null,
      n_no_source: rows.filter(function (r) { return r.functional_points === 0; }).length,
      national_people_per_point: totalFunctional ? totalPop / totalFunctional : null,
    };
  }

  /* --- water points --------------------------------------------------------- */

  function wpFirst(record, keys) {
    for (var i = 0; i < keys.length; i++) {
      var variants = [keys[i], '#' + keys[i]];
      for (var v = 0; v < variants.length; v++) {
        if (variants[v] in record) {
          var value = record[variants[v]];
          if (value !== null && value !== undefined && value !== '') return value;
        }
      }
    }
    return null;
  }

  /** status_clean text is authoritative when present; status_id is the
   * fallback. A source that is functional but needs repair still delivers
   * water, so it counts as functional.
   * @param {*} statusText
   * @param {*} [statusId]
   * @returns {boolean|null}
   */
  function functionalFrom(statusText, statusId) {
    var text = String(statusText || '').trim().toLowerCase();
    if (text) {
      if (text.indexOf('non') >= 0 || text.indexOf('not functional') >= 0 ||
          text.indexOf('abandoned') >= 0) {
        return false;
      }
      /* whole word, so "functionality" in "unknown functionality" does not
       * read as functional */
      /** @type {string[]} */
      var words = text.match(/[a-z]+/g) || [];
      if (words.indexOf('functional') >= 0) return true;
    }
    var sid = String(statusId === null || statusId === undefined ? '' : statusId)
      .trim().toLowerCase();
    if (['yes', 'y', 'true', '1'].indexOf(sid) >= 0) return true;
    if (['no', 'n', 'false', '0'].indexOf(sid) >= 0) return false;
    return null;
  }

  /* An improved source is worth rehabilitating; an unprotected well or spring
   * or surface water is not, so it is no alternative to a new borehole.
   *
   * The unimproved test runs first because "unprotected" contains "protected":
   * a Protected Spring is improved, an Unprotected Spring is not, and both
   * have to resolve correctly. Source and technology are read together, since
   * WPDx records "Well" in one column and "Hand Pump" in the other. */
  var UNIMPROVED_WORDS = ['unprotected', 'unimproved', 'open well', 'open dug',
    'surface', 'river', 'stream', 'pond', 'rainwater'];
  var IMPROVED_WORDS = ['borehole', 'tubewell', 'tube well', 'protected',
    'piped', 'hand pump', 'handpump', 'mechani'];

  /**
   * @param {*} source
   * @param {*} [technology]
   * @returns {boolean}
   */
  function improvedSource(source, technology) {
    var text = (String(source || '') + ' ' + String(technology || '')).toLowerCase();
    var i;
    for (i = 0; i < UNIMPROVED_WORDS.length; i++) {
      if (text.indexOf(UNIMPROVED_WORDS[i]) >= 0) return false;
    }
    for (i = 0; i < IMPROVED_WORDS.length; i++) {
      if (text.indexOf(IMPROVED_WORDS[i]) >= 0) return true;
    }
    return false;
  }

  /* The year out of a date as WPDx writes it. Exports carry ISO timestamps,
   * dd/mm/yyyy and bare years depending on who assembled them, so the year is
   * the first four-digit number in a plausible range rather than a format. */
  function wpYearOf(value) {
    var text = String(value === null || value === undefined ? '' : value).trim();
    if (!text) return null;
    var found = text.match(/\d{4}/g) || [];
    for (var i = 0; i < found.length; i++) {
      var year = Number(found[i]);
      if (year >= 1960 && year <= 2100) return year;
    }
    return null;
  }

  /* A number as an export writes one: digits with an optional sign, decimal
   * point and exponent, between the white space trim() takes off
   * (waterpoints._PLAIN_NUMBER, between its _EDGE_SPACE). Number() and
   * Python's float() read different cells as numbers: Number() takes "0x1F"
   * and reads a cell of spaces as 0, float() takes "nan", "inf" and "1_000". */
  var WP_PLAIN_NUMBER = /^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$/;

  /* A finite number out of a cell, or null: a JSON number as it is, a text
   * only when it is a plain decimal number, and nothing else (a boolean, a
   * blank, "Infinity", "1e999"): waterpoints._plain_number. */
  function wpPlainNumber(value) {
    var number;
    if (typeof value === 'number') {
      number = value;
    } else if (typeof value === 'string') {
      var text = value.trim();
      if (!WP_PLAIN_NUMBER.test(text)) return null;
      number = Number(text);
    } else {
      return null;
    }
    return isFinite(number) ? number : null;
  }

  /* The year a point was installed, or null when it is unrecorded: its whole
   * part, as the year 2009.6 falls in is 2009, and nothing at or below 0,
   * which WPDx exports write where the year was never recorded
   * (waterpoints._install_year). */
  function wpInstallYear(value) {
    var number = wpPlainNumber(value);
    if (number === null) return null;
    var year = Math.trunc(number);
    return year > 0 ? year : null;
  }

  /* Months of the year a point yields water. null is deliberately not twelve:
   * most surveys never asked, and reading silence as a year-round supply is
   * how a dry-season coverage figure ends up matching the wet-season one. */
  function wpMonthsPerYear(value) {
    var text = String(value === null || value === undefined ? '' : value)
      .trim().toLowerCase();
    if (!text) return null;
    if (['yes', 'year round', 'year-round', 'all year', 'permanent']
      .indexOf(text) >= 0) return 12;
    if (text === 'no' || text === 'seasonal') return null;
    var match = /\d+/.exec(text);
    if (!match) return null;
    var months = Number(match[0]);
    return months >= 0 && months <= 12 ? months : null;
  }

  /** `skipped` is optional and is how the page finds out what this threw away.
   * A record with no usable position cannot be counted against a chiefdom or
   * measured from a site, so dropping it is right - but an export that is half
   * unusable and an export that is complete produce the same answer on the
   * page, and the difference decides whether a community reads as served.
   * @param {Array<*>|null} records WPdx+ rows, from the API or a CSV
   * @param {Rec[]} [skipped] receives a flag saying what was dropped, and why
   * @returns {WaterPoint[]}
   */
  function parseWpdxRecords(records, skipped) {
    var out = [];
    var unplaced = 0;
    var unreadable = 0;
    (records || []).forEach(function (record) {
      if (!record || typeof record !== 'object') { unreadable += 1; return; }
      /* Number(null), Number('') and Number(' ') are all 0, and a CSV export
       * of WPdx+ is full of blanks. Left alone they became water points in
       * the Gulf of Guinea, counted in the coverage of whatever chiefdom was
       * nearest; a position no map holds ("NaN", UTM metres in the degree
       * columns) is set aside with them, by the rule the Python reader
       * follows. */
      var lat = wpPlainNumber(wpFirst(record, ['lat_deg', 'latitude', 'lat']));
      var lon = wpPlainNumber(wpFirst(record, ['lon_deg', 'longitude', 'lon']));
      if (lat === null || lon === null || Math.abs(lat) > 90 || Math.abs(lon) > 180) {
        unplaced += 1; return;
      }
      var source = String(wpFirst(record, ['water_source_clean', 'water_source',
        'source']) || '');
      var technology = String(wpFirst(record, ['water_tech_clean', 'water_tech',
        'technology']) || '');
      var statusText = String(wpFirst(record, ['status_clean', 'status']) || '');
      var statusId = wpFirst(record, ['status_id', 'status']);
      out.push({
        row_id: String(wpFirst(record, ['row_id', 'wpdx_id', 'objectid']) || ''),
        lat: lat, lon: lon,
        /* the technology stands in when the source column is blank, so a row
         * that only says "Hand Pump" still reads as a point rather than a
         * nameless dot */
        source: source || technology,
        technology: technology,
        status_text: statusText,
        functional: functionalFrom(statusText, statusId),
        improved: improvedSource(source, technology),
        installed: wpInstallYear(wpFirst(record, ['install_year', 'installation_year'])),
        /* when it was last surveyed, and how much of the year it yields
         * water. A point reported functional in 2016 is evidence about 2016,
         * and a null month count is not twelve. */
        report_year: wpYearOf(wpFirst(record, ['report_date', 'date_of_record',
          'survey_date', 'created_timestamp'])),
        months_per_year: wpMonthsPerYear(wpFirst(record, ['months_year',
          '#months_year', 'months_of_year', 'water_point_seasonality'])),
        adm2: String(wpFirst(record, ['clean_adm2', 'adm2']) || ''),
        name: String(wpFirst(record, ['water_source_description', 'source_name',
          'clean_adm4', 'clean_adm3']) || ''),
        distance_m: null,
      });
    });
    if (skipped) {
      if (unplaced) {
        skipped.push({ level: 'warning', code: 'water_point_unplaced',
          message: unplaced + ' inventory record(s) carry no usable latitude ' +
            'and longitude and are not counted anywhere on this page.' });
      }
      if (unreadable) {
        skipped.push({ level: 'warning', code: 'water_point_unreadable',
          message: unreadable + ' inventory record(s) could not be read at all.' });
      }
    }
    return out;
  }

  /* --- the live Water Point Data Exchange query ------------------------------
   *
   * groundwater/waterpoints.py fetch_water_points, in the browser. A bounding
   * box on the standard lat_deg/lon_deg columns (rather than a Socrata
   * within_circle on a geo column) so the request does not depend on a
   * particular geometry field name; the true radius is applied client side by
   * pointsWithin, exactly as the Python does.
   *
   * The whole call is optional. It is the only thing in this application that
   * touches the network, and it fails soft: offline, blocked by a browser
   * extension or refused by the CDN, the page says so and the CSV upload path
   * still does the whole job. */
  /**
   * @param {number} lat
   * @param {number} lon
   * @param {number} radiusM
   * @param {Rec} [options] limit, domain, resource
   * @returns {string}
   */
  function wpdxUrl(lat, lon, radiusM, options) {
    var opts = options || {};
    var limit = opts.limit || 5000;
    var dlat = radiusM / 111320.0;
    var dlon = radiusM / (111320.0 * Math.max(Math.cos(lat * Math.PI / 180), 1e-6));
    var where = 'lat_deg between ' + (lat - dlat) + ' and ' + (lat + dlat) +
      ' AND lon_deg between ' + (lon - dlon) + ' and ' + (lon + dlon);
    var query = '$where=' + encodeURIComponent(where) +
      '&$limit=' + Math.round(limit) +
      /* $order by the Socrata row id makes a capped result deterministic
       * across runs: a truncated slice is at least the same slice. */
      '&$order=' + encodeURIComponent(':id');
    return 'https://' + (opts.domain || WPDX_DOMAIN) + '/resource/' +
      (opts.resource || WPDX_RESOURCE) + '.json?' + query;
  }

  function WaterPointFetchError(message) {
    var error = new Error(message);
    error.name = 'WaterPointFetchError';
    return error;
  }

  /**
   * @param {number} lat
   * @param {number} lon
   * @param {number} [radiusM]
   * @param {Rec} [options] limit, domain, resource, timeoutS
   * @returns {Promise<Array<*>>}
   */
  async function fetchWaterPoints(lat, lon, radiusM, options) {
    var opts = options || {};
    var url = wpdxUrl(lat, lon, radiusM || DEFAULT_SEARCH_RADIUS_M, opts);
    var controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var timer = controller
      ? setTimeout(function () { /** @type {AbortController} */ (controller).abort(); }, (opts.timeoutS || 30) * 1000)
      : null;
    var response;
    try {
      response = await fetch(url, {
        headers: { Accept: 'application/json' },
        signal: controller ? controller.signal : undefined,
      });
    } catch (e) {
      throw WaterPointFetchError(
        'Could not reach the Water Point Data Exchange (' +
        (e && e.name === 'AbortError' ? 'the request timed out'
          : 'no network route, or the browser blocked the cross-origin request') +
        ').');
    } finally {
      if (timer) clearTimeout(timer);
    }
    if (!response.ok) {
      throw WaterPointFetchError(
        'The Water Point Data Exchange answered ' + response.status + ' ' +
        (response.statusText || '') + '.');
    }
    var data;
    try {
      data = await response.json();
    } catch (e) {
      throw WaterPointFetchError(
        'The Water Point Data Exchange sent something that is not JSON.');
    }
    if (!Array.isArray(data)) {
      throw WaterPointFetchError(
        'Unexpected response from the Water Point Data Exchange ' +
        '(expected a list of records).');
    }
    return data;
  }

  /** Fetch, parse and distance-filter in one call.
   *
   * The query is a bounding box, so it returns the corners of the square as
   * well as the circle the operator asked for. Without this last step a point
   * 1.4 km away lands in a 1 km search: the rehabilitate-or-drill decision
   * re-filters and would ignore it, but the functionality totals and anything
   * built on the stored inventory would silently count it.
   * @param {number} lat
   * @param {number} lon
   * @param {number} [radiusM]
   * @param {Rec} [options]
   * @param {Rec[]} [skipped]
   */
  async function waterPointsNear(lat, lon, radiusM, options, skipped) {
    var radius = radiusM || DEFAULT_SEARCH_RADIUS_M;
    var raw = await fetchWaterPoints(lat, lon, radius, options);
    return pointsWithin(parseWpdxRecords(raw, skipped), lat, lon, radius);
  }

  /**
   * @param {WaterPoint[]} points
   * @param {number} lat
   * @param {number} lon
   * @param {number} radiusM
   * @returns {WaterPoint[]}
   */
  function pointsWithin(points, lat, lon, radiusM) {
    var out = [];
    points.forEach(function (point) {
      var distance = haversineM(lat, lon, point.lat, point.lon);
      if (distance <= radiusM) {
        out.push(Object.assign({}, point, { distance_m: distance }));
      }
    });
    out.sort(function (a, b) { return a.distance_m - b.distance_m; });
    return out;
  }

  /** @param {WaterPoint[]} points */
  function functionalitySummary(points) {
    var functional = points.filter(function (p) { return p.functional === true; }).length;
    var nonFunctional = points.filter(function (p) { return p.functional === false; }).length;
    var unknown = points.filter(function (p) { return p.functional === null; }).length;
    var reported = functional + nonFunctional;
    return {
      total: points.length, functional: functional, non_functional: nonFunctional,
      unknown: unknown,
      functional_rate: reported ? (functional / reported * 100.0) : null,
    };
  }

  /** A working improved source inside the service radius means the community
   * may already be served; otherwise a broken improved source nearby is a
   * rehabilitation candidate, usually cheaper than a new borehole; otherwise
   * new construction is justified.
   * @param {WaterPoint[]} points
   * @param {number} lat
   * @param {number} lon
   * @param {Rec} [options] searchRadiusM, serviceRadiusM
   */
  function rehabVsDrill(points, lat, lon, options) {
    var opts = options || {};
    var searchRadius = opts.searchRadiusM || DEFAULT_SEARCH_RADIUS_M;
    var serviceRadius = opts.serviceRadiusM || SERVICE_RADIUS_M;
    var nearby = pointsWithin(points, lat, lon, searchRadius);
    var functional = nearby.filter(function (p) { return p.functional === true; });
    var brokenImproved = nearby.filter(function (p) {
      return p.functional === false && p.improved;
    });
    var served = functional.filter(function (p) {
      return p.improved && p.distance_m <= serviceRadius;
    });

    var common = {
      n_nearby: nearby.length, search_radius_m: searchRadius,
      service_radius_m: serviceRadius, summary: functionalitySummary(nearby),
      rehab_candidates: brokenImproved, nearby: nearby,
    };

    if (served.length) {
      var nearest = served[0];
      return Object.assign(common, {
        recommendation: VERIFY_NEED,
        headline: 'A working ' + (nearest.source || 'improved source') +
          ' is already ' + Math.round(nearest.distance_m) + ' m away.',
        rationale: 'An improved, functional source sits inside the ' +
          Math.round(serviceRadius) + ' m service radius, so the site may ' +
          'already be served. Confirm demand (population, queue times, ' +
          'dry-season reliability) before committing to a new borehole.',
      });
    }
    if (brokenImproved.length) {
      var broken = brokenImproved[0];
      return Object.assign(common, {
        recommendation: ASSESS_REHAB,
        headline: 'A non-functional ' + (broken.source || 'improved source') +
          ' lies ' + Math.round(broken.distance_m) + ' m away.',
        rationale: 'Rehabilitating a broken improved source is usually cheaper ' +
          'and faster than a new borehole. Assess why it failed - a dry or ' +
          'collapsed hole is not worth rehabilitating, a failed pump usually is ' +
          '- before deciding.',
      });
    }
    if (!nearby.length) {
      return Object.assign(common, {
        recommendation: DRILL_NEW,
        headline: 'No mapped water point within ' + Math.round(searchRadius) + ' m.',
        rationale: 'No existing water point is mapped near the site, so new ' +
          'construction is likely justified. Field-verify, since the water ' +
          'point inventory is not exhaustive.',
      });
    }
    /* Something is nearby but none of it is a rehabilitation alternative.
     * Which of the two reasons applies matters to the reader, so say the
     * right one rather than assuming distance every time. */
    var nearestWorking = functional[0];
    var note = '';
    if (nearestWorking) {
      note = nearestWorking.distance_m > serviceRadius
        ? ' The nearest working source is ' + Math.round(nearestWorking.distance_m) +
          ' m away, beyond the ' + Math.round(serviceRadius) + ' m service radius.'
        : ' The nearest working source is ' + Math.round(nearestWorking.distance_m) +
          ' m away but is not an improved source suitable for rehabilitation.';
    }
    return Object.assign(common, {
      recommendation: DRILL_NEW,
      headline: 'No rehabilitation candidate nearby.' + note,
      rationale: 'Nearby points are either working but beyond the service ' +
        'radius or not improved sources, so there is no cheaper rehabilitation ' +
        'alternative. New construction is reasonable.' + note,
    });
  }

  Object.assign(C, {
    EARTH_RADIUS_M: EARTH_RADIUS_M,
    DEFAULT_SEARCH_RADIUS_M: DEFAULT_SEARCH_RADIUS_M,
    SERVICE_RADIUS_M: SERVICE_RADIUS_M,
    DRILL_NEW: DRILL_NEW, ASSESS_REHAB: ASSESS_REHAB, VERIFY_NEED: VERIFY_NEED,
    WPDX_CREDIT: WPDX_CREDIT, POPULATION_CREDIT: POPULATION_CREDIT,
    haversineM: haversineM, pointInRing: pointInRing, loadPolygons: loadPolygons,
    geoLayers: geoLayers,
    polyContains: polyContains, chiefdomOfPoint: chiefdomOfPoint,
    CHIEFDOM_EDGE_TOLERANCE_M: CHIEFDOM_EDGE_TOLERANCE_M,
    ringDistanceM: ringDistanceM, nearestChiefdomIndex: nearestChiefdomIndex,
    outerRingSets: outerRingSets,
    DISTRICT_EDGE_TOLERANCE_M: DISTRICT_EDGE_TOLERANCE_M,
    nearDistricts: nearDistricts,
    loadDistrictPopulation: loadDistrictPopulation,
    loadChiefdomDistrict: loadChiefdomDistrict,
    districtNames: districtNames, matchDistrict: matchDistrict,
    districtsNamed: districtsNamed, orList: orList,
    districtDisplayName: districtDisplayName, districtLabel: districtLabel,
    chiefdomPopulation: chiefdomPopulation,
    countPointsByChiefdom: countPointsByChiefdom,
    countPointsByDistrict: countPointsByDistrict,
    groupPointsByDistrict: groupPointsByDistrict,
    groupPointsByChiefdom: groupPointsByChiefdom,
    coverageRows: coverageRows, chiefdomCoverageRows: chiefdomCoverageRows,
    loadServiceClasses: loadServiceClasses,
    coverageStats: coverageStats,
    parseWpdxRecords: parseWpdxRecords, pointsWithin: pointsWithin,
    functionalitySummary: functionalitySummary, rehabVsDrill: rehabVsDrill,
    functionalFrom: functionalFrom,
    improvedSource: improvedSource,
    WPDX_DOMAIN: WPDX_DOMAIN, WPDX_RESOURCE: WPDX_RESOURCE,
    wpdxUrl: wpdxUrl, fetchWaterPoints: fetchWaterPoints,
    waterPointsNear: waterPointsNear,
  });

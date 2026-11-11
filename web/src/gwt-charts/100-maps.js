
  /* ===================================================================== maps
   *
   * Every map in the toolkit is drawn by the three functions below, and every
   * one of them gets the same furniture: a neatline, a graticule with its
   * coordinates written on it, a scale bar in kilometres, a north arrow, a
   * legend in its own panel below the frame, and the credit for the data.
   *
   * The furniture is not decoration. A map of a district with no scale on it
   * cannot be used to judge whether the next village is 3 km away or 30, and
   * a map with no coordinates on it cannot be checked against a GPS. These
   * figures go into reports that someone has to act on, so they carry what a
   * map has to carry to be acted on.
   *
   * The legend sits below the frame rather than on it. Drawn inside, it
   * covered whatever happened to be in that corner, and there is no corner of
   * a national map that is reliably empty.
   */

  var MAP_NO_DATA = '#EFEDE6';
  /* The Python engine holds the same two in groundwater/mapping/cartography.py
   * as SEA and NOT_MAPPED; change one and change the other. They are kept
   * apart on purpose: sea and a hole in the source layer are different
   * things, and painting both the same tint is how a coverage gap along the
   * Bullom shore reads as ocean. */
  var MAP_SEA = '#D9E6EF';
  var MAP_NOT_MAPPED = '#EDEBE7';
  /* The land across the border, and the neutral fill under an administrative
   * map: carto.FOREIGN_LAND and carto.LAND in the Python engine. Guinea and
   * Liberia used to take the same blue as the Atlantic on every map, so a
   * site near the northern border looked like a site on the coast. */
  var MAP_FOREIGN_LAND = '#F2F0EC';
  var MAP_LAND = '#FBFAF8';

  /* A muted geological palette, keyed by the bundled USGS unit code. The
   * Python engine reads the same table in groundwater/mapping/cartography.py
   * as GEOLOGY_COLOURS; change one and change the other, or a report figure
   * and the screen figure of the same site come out different colours and a
   * reader holding both cannot line them up.
   *
   * The colours carried in the data are the USGS sheet's own - pure blue,
   * magenta, red - and three saturated hues fighting each other is what made
   * these read as a school atlas. The aquifer layer keeps its source colours,
   * because there the colour IS the classification.
   *
   * Each tint is at least 0.05 of relative luminance from every other and
   * from the sea, the paper and the not-mapped tone, so the units stay apart
   * in greyscale. The Bullom Group was 0.77 against a sea of 0.78 and
   * vanished into the Atlantic on a photocopy, which is how most of these
   * reports are actually read in the field. */
  var GEOLOGY_COLOURS = {
    pCm: '#CDBAC6', Pi: '#B7715C', Mi: '#CC9A86',
    O: '#9DB9A3', S: '#BCCDB6', Qe: '#E6D5A6', H2O: '#6F9BBF',
  };

  /* sRGB relative luminance, 0 (black) to 1 (white): what a photocopy keeps.
   * The same arithmetic as relative_luminance in the Python engine, so the
   * separation above can be held to the same figure on either side. */
  function relativeLuminance(colour) {
    var hex = String(colour).replace('#', '');
    var lin = [0, 2, 4].map(function (i) {
      var c = parseInt(hex.substr(i, 2), 16) / 255;
      return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
  }

  function unitColour(props, spec) {
    if (spec && spec.sourceColours) return props.color || palette().neutral;
    return GEOLOGY_COLOURS[props.glg] || props.color || palette().neutral;
  }

  /* Youngest first, oldest last, and the things that are not rocks after
   * both: the order a map key is read in, and _ERA_ORDER in the Python
   * engine. Anything the list does not name ranks after all of it. */
  var ERA_ORDER = ['Cenozoic', 'Mesozoic', 'Paleozoic', 'Precambrian',
    'Non-geological'];

  /* The era and the source code one key entry is ranked by. The geology
   * layer carries them as `era` and `glg`; the aquifer layer carries the
   * same two as `geology` and `code`, which is where load_hydrogeology reads
   * them from in the Python engine. Sorting the key alphabetically by label
   * instead put "Surface water" between two aquifer classes on the national
   * aquifer map, where the Python key ends on it. */
  function eraRank(props) {
    var found = ERA_ORDER.indexOf(props.era || props.geology || '');
    return found < 0 ? 99 : found;
  }

  function unitCode(props) {
    return String(props.glg || props.code || '');
  }

  /* Which crosswalk region a district belongs to, what the ground is for one
   * USGS class there, and which district a polygon lies in. They live in the
   * engine, gwt-core.js, because the geophysical report's geology paragraph
   * reads them too: the key on the map and the paragraph beside it name one
   * polygon one way, and the parity suite holds the paragraph to the
   * Python's. */
  var regionOf = C.lithologyRegionOf;
  var lithologyFor = C.lithologyFor;
  var unitDistrict = C.unitDistrict;

  /* Centroid of a ring, by the shoelace formula. */
  function ringCentroid(ring) {
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

  /* The name to put in a map key: the formation first, then its own code,
   * then the USGS code the polygon was actually drawn from. The last is not
   * decoration - a 1:600,000 name sitting on a 1:5,000,000 line invites the
   * reader to trust the line at 1:600,000. Matches Lithology.legend_label.
   *
   * `district` is where the polygon is, which the caller works out; the
   * site's own district is only the fallback for a polygon that could not
   * be placed. */
  function unitLabel(props, spec, district) {
    var source = String(props.unit || 'unclassified');
    if (!spec || !spec.nameLithology) return source;
    /* A class the crosswalk has nothing to say about keeps the source's own
     * wording, and on these maps it keeps the code beside it - label_with_code
     * in the Python engine, which the unit maps that name lithology pass and
     * the aquifer map does not. Dropping the code left a key entry reading
     * "Holocene" where the Python one reads "Holocene (Qe)", with nothing on
     * the figure tying the colour back to the layer it was drawn from. */
    var fallback = props.glg ? source + ' (' + props.glg + ')' : source;
    var rock = lithologyFor(props.glg,
      district === undefined ? spec.district : district);
    if (!rock || !rock.formation_name) return fallback;
    var codes = [];
    if (rock.formation_code) codes.push(rock.formation_code.replace(/;/g, ', '));
    if (props.glg) codes.push('USGS ' + props.glg);
    return rock.formation_name +
      (codes.length ? ' (' + codes.join('; ') + ')' : '');
  }

  /* One line a figure carries about a class whose source age is wrong. The
   * age is not quietly rewritten: both are shown and the note says which is
   * which, because correcting somebody else's dataset in silence leaves a
   * reader unable to tell what they are looking at. */
  function lithologyNote(props, spec, district) {
    if (!spec || !spec.nameLithology) return '';
    var rock = lithologyFor(props.glg,
      district === undefined ? spec.district : district);
    if (!rock || String(rock.usgs_era_wrong).toLowerCase() !== 'yes') return '';
    return 'The source layer dates this polygon as ' + props.unit + '; it is ' +
      'the ' + rock.formation_name + ', ' + rock.era_actual + '. The boundary ' +
      'is the 1:5,000,000 one either way.';
  }

  function featureBounds(features) {
    var b = { lonMin: Infinity, lonMax: -Infinity, latMin: Infinity, latMax: -Infinity };
    function scan(coords) {
      if (typeof coords[0] === 'number') {
        if (coords[0] < b.lonMin) b.lonMin = coords[0];
        if (coords[0] > b.lonMax) b.lonMax = coords[0];
        if (coords[1] < b.latMin) b.latMin = coords[1];
        if (coords[1] > b.latMax) b.latMax = coords[1];
        return;
      }
      coords.forEach(scan);
    }
    features.forEach(function (f) {
      if (f && f.geometry && f.geometry.coordinates) scan(f.geometry.coordinates);
    });
    return b;
  }

  /* Equirectangular, scaled about the middle latitude of the extent. Over a
   * district or a country this is within a percent of a conformal projection
   * and it keeps north up and the arithmetic invertible, which is what the
   * scale bar and the graticule need. */
  function projectionInto(features, rect, pad) {
    var b = featureBounds(features);
    var padPx = pad === undefined ? 0 : pad;
    if (!isFinite(b.lonMin)) {
      b = { lonMin: -13.4, lonMax: -10.2, latMin: 6.9, latMax: 10.0 };
    }
    if (b.lonMax - b.lonMin < 1e-6) { b.lonMin -= 0.02; b.lonMax += 0.02; }
    if (b.latMax - b.latMin < 1e-6) { b.latMin -= 0.02; b.latMax += 0.02; }
    var midLat = (b.latMin + b.latMax) / 2;
    var kx = Math.cos(midLat * Math.PI / 180);
    var w = (b.lonMax - b.lonMin) * kx, h = b.latMax - b.latMin;
    var innerW = rect.w - 2 * padPx, innerH = rect.h - 2 * padPx;
    var scale = Math.min(innerW / w, innerH / h);
    var ox = rect.x + padPx + (innerW - w * scale) / 2;
    var oy = rect.y + padPx + (innerH - h * scale) / 2;

    function project(lon, lat) {
      return [ox + (lon - b.lonMin) * kx * scale, oy + (b.latMax - lat) * scale];
    }
    project.scale = scale;
    project.kx = kx;
    /* one degree of longitude at the middle latitude, divided by the pixels
     * it occupies: the number the scale bar is built from */
    project.metresPerPx = 111320 / scale;
    project.bounds = b;
    project.rect = rect;
    project.invert = function (x, y) {
      return [b.lonMin + (x - ox) / (kx * scale), b.latMax - (y - oy) / scale];
    };
    /* [lonMin, latMin, lonMax, latMax] of everything the frame shows */
    project.visibleBox = function () {
      var sw = project.invert(rect.x, rect.y + rect.h);
      var ne = project.invert(rect.x + rect.w, rect.y);
      return [sw[0], sw[1], ne[0], ne[1]];
    };
    return project;
  }

  /* Kept for callers outside this file; the layout-aware form is the one the
   * maps below use. */
  function mapProjection(features, width, height, padding) {
    var pad = padding === undefined ? 18 : padding;
    return projectionInto(features, { x: 0, y: 0, w: width, h: height }, pad);
  }

  function geometryPath(geometry, project) {
    var parts = [];
    function ring(coords) {
      parts.push(coords.map(function (c, i) {
        var pt = project(c[0], c[1]);
        return (i ? 'L' : 'M') + pt[0].toFixed(1) + ' ' + pt[1].toFixed(1);
      }).join(' ') + 'Z');
    }
    if (!geometry) return '';
    if (geometry.type === 'Polygon') geometry.coordinates.forEach(ring);
    else if (geometry.type === 'MultiPolygon') {
      geometry.coordinates.forEach(function (poly) { poly.forEach(ring); });
    }
    return parts.join(' ');
  }

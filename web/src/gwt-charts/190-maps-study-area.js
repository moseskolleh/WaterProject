
  /* ------------------------------------------------------- study area map */

  /* Marker and colour per kind of thing on a study area map. The Python
   * engine reads the same table in groundwater/mapping/regional.py; change
   * one and change the other, or the two engines draw the same survey with
   * different symbols and a reader holding both reports cannot line them up. */
  /* the sounding the survey recommends drilling at: the one marker on a
   * siting map that has to be unmistakable */
  var AREA_MARKERS = {
    'recommended point': { kind: 'star', colour: '#B00020', size: 8 },
    'VES point': { kind: 'triangle', colour: '#1F5C8B' },
    borehole: { kind: 'circle', colour: '#0F7B3F' },
    'water point': { kind: 'square', colour: '#7B5AA6' },
    settlement: { kind: 'circle', colour: '#555555' },
  };

  /* A thumbnail of the country with the study area boxed on it, drawn into
   * the corner of the frame that carries the fewest points. A 20 km map is
   * unreadable as a location unless the reader already knows the district;
   * the inset is what makes the figure answer "where is this?" as well as
   * "what is here?". */
  function locatorInset(canvas, outline, window_, corner) {
    /* the plate and the box the place names are kept out of are one
     * rectangle, read from the same table, so a name cannot be dropped for
     * furniture that turns out to sit somewhere else */
    var plate = insetRect(canvas.rect, corner);
    var x = plate.x, y = plate.y, w = plate.w, h = plate.h;
    var p = canvas.palette;
    var titleH = 12;
    var group = svgEl('g');
    group.appendChild(svgEl('rect', {
      x: x, y: y, width: w, height: h, fill: p.surface, opacity: 0.95,
      stroke: '#888888', 'stroke-width': 0.8,
    }));
    /* the caption goes inside the plate, not above it: above it lands on
     * the map frame and gets clipped by it */
    group.appendChild(svgEl('text', {
      x: x + w / 2, y: y + titleH - 3, 'text-anchor': 'middle', 'font-size': 8,
      'font-weight': 620, fill: p.ink, text: 'Sierra Leone',
    }));
    var project = projectionInto(
      outline, { x: x, y: y + titleH, w: w, h: h - titleH }, 4);
    outline.forEach(function (feature) {
      group.appendChild(svgEl('path', {
        d: geometryPath(feature.geometry, project),
        fill: '#EDF2F7', stroke: '#333333', 'stroke-width': 0.7,
      }));
    });
    if (window_) {
      var dLat = window_.radiusKm / 111.320;
      var dLon = window_.radiusKm /
        (111.320 * Math.max(Math.cos(window_.lat * Math.PI / 180), 1e-6));
      var a = project(window_.lon - dLon, window_.lat + dLat);
      var b = project(window_.lon + dLon, window_.lat - dLat);
      var bw = Math.abs(b[0] - a[0]), bh = Math.abs(b[1] - a[1]);
      /* below about four pixels a box is a smudge; a dot reads as a place */
      if (bw > 4 && bh > 4) {
        group.appendChild(svgEl('rect', {
          x: a[0], y: a[1], width: bw, height: bh, fill: 'none',
          stroke: '#C1272D', 'stroke-width': 1.4,
        }));
      } else {
        var c = project(window_.lon, window_.lat);
        group.appendChild(svgEl('circle', {
          cx: c[0], cy: c[1], r: 3, fill: '#C1272D', stroke: p.surface,
          'stroke-width': 0.9,
        }));
      }
    }
    canvas.svg.appendChild(group);
  }

  /* The two corners the furniture can have, emptiest first: the inset takes
   * the first and the key the second. Fixing them to a corner drew a survey
   * point underneath the inset on the first real site this was tried on.
   *
   * Counted from the DATA alone, as _corner_occupancy does in the Python
   * engine: counting place names as occupancy put the inset on top of a
   * survey point, because three droppable labels in one corner outvoted the
   * one thing on the map that cannot move. The scale bar owns the lower
   * left and the north arrow the upper right, so these two are what is
   * left, and on a tie the inset keeps the lower right. */
  function freeMapCorners(canvas, points) {
    var rect = canvas.rect;
    var counts = { 'lower right': 0, 'upper left': 0 };
    (points || []).forEach(function (point) {
      var pt = canvas.project(point.lon, point.lat);
      var fx = (pt[0] - rect.x) / rect.w, fy = (pt[1] - rect.y) / rect.h;
      if (fx > 0.62 && fy > 0.58) counts['lower right'] += 1;
      if (fx < 0.38 && fy < 0.42) counts['upper left'] += 1;
    });
    return counts['lower right'] <= counts['upper left']
      ? ['lower right', 'upper left'] : ['upper left', 'lower right'];
  }

  /* The chiefdoms the bundled boundary layer truncated to fifteen
   * characters. "Sanda Magbolont" and "Bureh Kasseh Ma" went onto client
   * maps that way; the layer name stays the key every crosswalk joins on,
   * and this is what is printed. The table is bundled as chiefdomNames, and
   * a bundle built before it existed simply leaves the layer's own spelling
   * on the map rather than dropping the name. chiefdom_full_names in the
   * Python engine. */
  function chiefdomFullNames() {
    var rows = ((GWT.data || {}).chiefdomNames) || [];
    var out = {};
    rows.forEach(function (row) {
      var layer = String(row.layer_name || '').trim();
      if (layer) out[layer] = String(row.full_name || '').trim() || layer;
    });
    return out;
  }

  function chiefdomLabel(name) {
    var layer = String(name || '').trim();
    return chiefdomFullNames()[layer] || layer;
  }

  /* A study-area map of a site with a fix spans this much either side of it
   * unless the overlay points need more: at 10 km the village, the
   * soundings and the recommended point are told apart, which at the old
   * fixed 40 km (an 80 km window) they never were. */
  var STUDY_AREA_RADIUS_KM = 10;
  var STUDY_AREA_CEILING_KM = 40;

  /* The half-width of the study-area map, from what has to fit on it.
   * study_area_radius_km in the Python engine, which the reports size their
   * window with; the ceiling is the local-window setting the caller asked
   * for, never the figure worked out here. */
  function studyAreaRadiusKm(centre, points, ceilingKm) {
    var ceiling = ceilingKm || STUDY_AREA_CEILING_KM;
    var lats = [], lons = [];
    function add(lat, lon) {
      if (lat === null || lat === undefined || lon === null || lon === undefined) return;
      lats.push(Number(lat)); lons.push(Number(lon));
    }
    if (centre) add(centre.lat, centre.lon);
    (points || []).forEach(function (point) { add(point.lat, point.lon); });
    if (lats.length < 2) return Math.min(STUDY_AREA_RADIUS_KM, ceiling);
    /* the map is centred on the site, so what has to fit is the farthest
     * point from it, not half the spread between the points */
    var cLat = centre ? Number(centre.lat) : 0, cLon = centre ? Number(centre.lon) : 0;
    if (!centre) {
      cLat = lats.reduce(function (a, b) { return a + b; }, 0) / lats.length;
      cLon = lons.reduce(function (a, b) { return a + b; }, 0) / lons.length;
    }
    var cos = Math.cos(cLat * Math.PI / 180);
    var farthest = 0;
    for (var i = 0; i < lats.length; i++) {
      farthest = Math.max(farthest, Math.sqrt(
        Math.pow((lats[i] - cLat) * 111.32, 2) +
        Math.pow((lons[i] - cLon) * 111.32 * cos, 2)));
    }
    /* the farthest point with a quarter of the frame to spare beyond it */
    return Math.min(Math.max(STUDY_AREA_RADIUS_KM, farthest * 1.25 + 1), ceiling);
  }

  /* The study area at a readable scale: the chiefdom boundaries around the
   * site, the survey points and any water points found nearby, with a
   * thumbnail of the country showing where in it this is. */
  function studyAreaMap(spec) {
    var window_ = spec.window || null;
    var outline = spec.outline || [];
    var points = (spec.points || []).slice();
    /* A site with a fix is mapped at the scale its own points need. The
     * window was hard-wired wide, so no report carried a map on which the
     * village, the soundings and the recommended point could be told
     * apart. An area window without a fix is already the size of the area
     * it is centred on and is left alone. */
    if (window_ && window_.exact) {
      window_ = Object.assign({}, window_, {
        radiusKm: studyAreaRadiusKm(window_, points,
          Math.min(window_.radiusKm, STUDY_AREA_CEILING_KM)),
      });
    }
    var dLat = window_ ? window_.radiusKm / 111.320 : 0.25;
    var dLon = window_
      ? window_.radiusKm /
        (111.320 * Math.max(Math.cos(window_.lat * Math.PI / 180), 1e-6))
      : 0.25;
    var box = window_
      ? [window_.lon - dLon, window_.lat - dLat,
        window_.lon + dLon, window_.lat + dLat]
      : null;
    /* the window sets the extent, so a 25 km map is a 25 km map even when a
     * chiefdom covering it runs half the length of the country */
    var extent = box
      ? [{ geometry: { type: 'Polygon', coordinates: [[
        [box[0], box[1]], [box[2], box[1]], [box[2], box[3]], [box[0], box[3]],
      ]] } }]
      : (spec.areas || []);

    var kinds = [];
    points.forEach(function (point) {
      var style = AREA_MARKERS[point.kind] || { kind: 'diamond', colour: '#C15A2A' };
      point.kind_ = point.kind || 'point';
      point.marker = style.kind;
      point.colour = point.colour || style.colour;
      if (!kinds.some(function (k) { return k.label === point.kind_; })) {
        kinds.push({ label: point.kind_, colour: style.colour, kind: style.kind });
      }
    });

    var canvas = mapCanvas(spec, kinds, extent);
    var p = canvas.palette;
    clipToFrame(canvas);
    var frame = box || canvas.project.visibleBox();
    seaAndNeighbours(canvas, outline, MAP_LAND, foreignLandFeatures(frame));

    function inBox(feature) {
      if (!box) return true;
      var b = featureBounds([feature]);
      return isFinite(b.lonMin) && b.lonMin <= box[2] && b.lonMax >= box[0] &&
        b.latMin <= box[3] && b.latMax >= box[1];
    }
    /* chiefdoms first: they are the boundaries a community is found by, and
     * their names are the only thing on this map that tells a reader which
     * side of a boundary the site is on */
    var named = [];
    (spec.areas || []).filter(inBox).forEach(function (feature) {
      var label = chiefdomLabel((feature.properties || {}).name);
      canvas.layer.appendChild(svgEl('path', {
        d: geometryPath(feature.geometry, canvas.project),
        fill: 'none', stroke: '#7E93A6', 'stroke-width': 0.8,
      }, [svgEl('title', { text: label })]));
      if (!box || !label) return;
      var drawn = ringsOf(feature.geometry).filter(function (ring) {
        return ringReachesBox(ring, box);
      });
      /* one label per chiefdom, on the part of it that is in view.
       * Labelling every ring wrote "Kaffu Bullom" five times across the top
       * of the first map this drew: the chiefdom reaches the window as five
       * islands, and each one asked for its own name. */
      var spot = labelSpot(drawn, box);
      if (!spot) return;
      named.push({
        candidate: [spot[0], spot[1], label],
        weight: drawn.reduce(function (sum, ring) {
          return sum + ringArea(ring);
        }, 0),
      });
    });
    (spec.districts || []).filter(inBox).forEach(function (feature) {
      canvas.layer.appendChild(svgEl('path', {
        d: geometryPath(feature.geometry, canvas.project),
        fill: 'none', stroke: '#44586B', 'stroke-width': 1.3,
      }));
    });
    outline.filter(inBox).forEach(function (feature) {
      canvas.layer.appendChild(svgEl('path', {
        d: geometryPath(feature.geometry, canvas.project),
        fill: 'none', stroke: '#222222', 'stroke-width': 1.8,
      }));
    });

    /* Where the furniture goes is settled before the names are placed, and
     * from the data alone. Both corners are kept clear of names: the inset
     * takes one, and the other is the key's - the browser prints the key
     * under the frame and the reports print it inside, and a name kept here
     * and dropped there is a pair of figures a reader cannot line up. */
    /* A point off the window does not occupy a corner of it. _corner_occupancy
     * skips anything outside the axis limits, and the frame is letterboxed
     * around the window here, so a water point a few kilometres past the
     * edge still lands in the margin the frame shows and would otherwise
     * vote the inset out of the corner it belongs in. */
    var located = points.filter(function (point) {
      return point.lon !== null && point.lon !== undefined &&
        point.lat !== null && point.lat !== undefined &&
        (!box || insideBox(point.lon, point.lat, box));
    });
    var free = freeMapCorners(canvas, located);
    var reserved = [furnitureBox(canvas, free[0])];
    if (points.length) reserved.push(furnitureBox(canvas, free[1]));
    var clear = named.filter(function (item) {
      return !reserved.some(function (r) {
        return insideBox(item.candidate[0], item.candidate[1], r);
      });
    });
    if (box) {
      declutter(clear.map(function (item) { return item.candidate; }), box, 0.05,
        clear.map(function (item) { return item.weight; })
      ).forEach(function (candidate) {
        var at = canvas.project(candidate[0], candidate[1]);
        placeMapLabel(canvas.layer, at[0], at[1] + 3, candidate[2], p,
          { size: 8, fill: p.muted });
      });
    }

    drawMapPoints(canvas, points.map(function (point) {
      return Object.assign({}, point, { kind: point.marker, size: 6 });
    }));
    locatorInset(canvas, outline, window_, free[0]);
    return canvas.finish();
  }


  /* ============================================================ terrain */

  /* The four figures of the terrain analysis (PLAN.md step 4.1): shaded
   * relief with the drainage lines, the wetness index, the two curvatures,
   * and the relief lit from each of the panel azimuths. terrain.py draws
   * the same four in the Python app. Each is drawn from what
   * C.terrainDisplayLayers gives - the layers cropped to the square shown
   * and thinned to at most 1024 cells a side, which is what the worker
   * hands the page - and from the parts, summary and captions the analysis
   * worked out, so the contour interval, the colour ranges, the lines and
   * the words on both apps' figures are the engine's.
   *
   * A layer this size is not drawn as SVG shapes: a million rectangles is a
   * figure nobody would wait for. rasterImage paints it into a canvas and
   * embeds the PNG in the SVG, which toPng rasterises with the rest and the
   * SVG download carries.
   *
   * figure() writes its caption in a <figcaption> outside the SVG, and the
   * PNG and SVG buttons export the SVG alone, so the credit the elevation
   * model's licence asks for and the line saying these are candidates, not
   * mapped features, are drawn inside every figure, where a downloaded copy
   * keeps them. */

  /* The fills of every terrain panel and the inks of its overlays: data
   * colours, not theme tokens, for the reason ON_RAMP_INK gives. Sea is one
   * pale blue whether it has a height or was taken from a missing tile, and
   * the second is hatched in a darker blue, because it has no height and a
   * reader should not take it for measured water. A void and a zero-filled
   * gap the analysis set aside are both a light grey: neither is ground. */
  var TERRAIN_SEA = 0xCFE3F2;
  var TERRAIN_SEA_HATCH = 0x9DBDD8;
  var TERRAIN_VOID = 0xE6E6E6;
  /* the tint over ground the fill raised by fill_note_m or more, at 0.25 */
  var TERRAIN_FILL_TINT = 0x7B5EA7;
  /* the drainage lines: a water blue that holds on every colour of the
   * land ramp, from its green to its white */
  var TERRAIN_LINE = '#1F5C99';
  /* plot_topographic_map's contour ink */
  var TERRAIN_CONTOUR = '#5A3A1E';
  /* _mark_site's colour on the topographic map */
  var TERRAIN_SITE = '#C1272D';
  /* the lineament candidates (mapping/terrain.py _VALLEY_COLOUR and
   * _RIDGE_COLOUR): a valley blue and a ridge orange, drawn 1.6 wide over
   * the grey relief lightened 40% towards white; and the rose's petals at
   * 85% and the shares of the longest band its rings are drawn at */
  var LINEAMENT_VALLEY = '#1D4E89';
  var LINEAMENT_RIDGE = '#C15A2A';
  var LINEAMENT_WIDTH = 1.6;
  var LINEAMENT_GROUND = 0.4;
  var PETAL_OPACITY = 0.85;
  var ROSE_RINGS = [0.25, 0.5, 0.75, 1.0];

  /* A packed 0xRRGGBB colour moved `f` of the way to `to`, each channel
   * rounded as mixHex rounds. */
  function mixPacked(from, to, f) {
    var r = (from >> 16) & 255, g = (from >> 8) & 255, b = from & 255;
    r = Math.round(r + (((to >> 16) & 255) - r) * f);
    g = Math.round(g + (((to >> 8) & 255) - g) * f);
    b = Math.round(b + ((to & 255) - b) * f);
    return (r << 16) | (g << 8) | b;
  }

  /* A ramp's 256 entries as packed colours, worked out once per ramp: a
   * figure of a million cells cannot afford a string per cell. */
  var rampTables = {};
  function rampTable(name) {
    var table = rampTables[name];
    if (!table) {
      table = new Int32Array(256);
      for (var i = 0; i < 256; i++) {
        var c = hexChannels(rampColour(name, (i + 0.5) / 256));
        table[i] = (c[0] << 16) | (c[1] << 8) | c[2];
      }
      rampTables[name] = table;
    }
    return table;
  }

  /* The entry of a 256-entry table that `value` takes on the scale lo to
   * hi, as matplotlib's Normalize and lookup pick it: clamped to the ends,
   * min(floor(t * 256), 255), and entry 0 on a scale with no width. */
  function rampEntry(value, lo, hi) {
    var t = hi > lo ? (value - lo) / (hi - lo) : 0;
    t = t > 0 ? (t < 1 ? t : 1) : 0;
    var entry = Math.floor(t * 256);
    return entry > 255 ? 255 : entry;
  }

  /**
   * A grid of cells as an SVG <image>: an RGBA canvas filled north row
   * first, so that canvas row y is layer row rows - 1 - y of a layer held
   * south row first, encoded as a PNG and placed at {x, y, width, height}
   * with preserveAspectRatio none, so a cell takes the shape the frame
   * gives it. A cell whose value is NaN is left transparent; colourOf is
   * asked about every other cell and gives its colour as 0xRRGGBB, or -1 to
   * leave it transparent too. It is handed the cell's index in `layer` and
   * its pixel on the canvas as well as its value, for a colour that reads
   * other layers or draws a pattern. It needs a canvas, so it draws on the
   * page, never in the worker.
   * @param {ArrayLike<number>} layer the cells, south row first, row-major
   * @param {number} rows
   * @param {number} cols
   * @param {(value: number, k: number, x: number, y: number) => number} colourOf
   * @param {{x: number, y: number, width: number, height: number}} box where the image goes, in the
   *   SVG's own units
   * @returns {SVGElement}
   */
  function rasterImage(layer, rows, cols, colourOf, box) {
    var canvas = document.createElement('canvas');
    canvas.width = cols;
    canvas.height = rows;
    var ctx = canvas.getContext('2d');
    var image = ctx.createImageData(cols, rows), px = image.data;
    for (var y = 0; y < rows; y++) {
      var k = (rows - 1 - y) * cols, at = 4 * y * cols;
      for (var x = 0; x < cols; x++, k++, at += 4) {
        var value = layer[k];
        if (value !== value) continue;
        var c = colourOf(value, k, x, y);
        if (!(c >= 0)) continue;
        px[at] = (c >> 16) & 255;
        px[at + 1] = (c >> 8) & 255;
        px[at + 2] = c & 255;
        px[at + 3] = 255;
      }
    }
    ctx.putImageData(image, 0, 0);
    return svgEl('image', {
      href: canvas.toDataURL('image/png'), x: box.x, y: box.y,
      width: box.width, height: box.height, preserveAspectRatio: 'none',
    });
  }

  /* The colour a terrain panel gives a cell that is not land - sea, sea
   * taken from a missing tile, hatched where ((x + y) mod 6) < 2, or a gap
   * - and -2 for land, which each panel colours itself. */
  function terrainGround(display, k, x, y) {
    var cls = display.cls[k];
    if (cls === 1) return -2;
    if (cls === 2) return display.assumedSea[k] && (x + y) % 6 < 2 ? TERRAIN_SEA_HATCH : TERRAIN_SEA;
    return TERRAIN_VOID;
  }

  /* Where the display's cells are in longitude and latitude. Row r and
   * column c of the analysed grid are at lat(r) and lon(c), worked out from
   * the kept cells' centres and the stride between them. The square shown
   * runs from the outer edges of its first and last rows and columns,
   * which is the square the analysis cut the lines to. */
  function terrainGeometry(display) {
    var shown = display.shown, stride = display.stride;
    var lons = display.lons, lats = display.lats;
    var sx = lons.length > 1 ? (lons[lons.length - 1] - lons[0]) / ((lons.length - 1) * stride) : NaN;
    var sy = lats.length > 1 ? (lats[lats.length - 1] - lats[0]) / ((lats.length - 1) * stride) : NaN;
    /* a square one kept cell across has no spacing of its own to give */
    if (!(sx > 0)) sx = sy > 0 ? sy : 1 / 3600;
    if (!(sy > 0)) sy = sx;
    var r0 = shown[0], c0 = shown[2];
    var west = lons[0] - sx / 2, south = lats[0] - sy / 2;
    return {
      west: west, east: west + (shown[3] - c0) * sx, south: south, north: south + (shown[1] - r0) * sy,
      sx: sx, sy: sy, r0: r0, c0: c0,
      lon: function (c) { return lons[0] + (c - c0) * sx; },
      lat: function (r) { return lats[0] + (r - r0) * sy; },
    };
  }

  /* One layer of the display as a raster in a panel. Each kept cell is
   * the first of the `stride` cells each way it stands for, and is drawn
   * over all of them, from the south-west corner of the square shown; a
   * side the stride does not divide runs past the square by less than a
   * block, which the panel's clip cuts off. Drawn three or more pixels to a
   * cell it is drawn as blocks, as matplotlib's default interpolation
   * switches to nearest when it enlarges an image that much: a cell is a
   * measurement of its whole square, and blurring classes into each other
   * would draw sea and gaps that are not there. */
  function terrainRaster(panel, display, geo, colourOf, name) {
    var s = display.stride;
    var a = panel.project(geo.west, geo.south + display.rows * s * geo.sy);
    var b = panel.project(geo.west + display.cols * s * geo.sx, geo.south);
    var image = rasterImage(display.cls, display.rows, display.cols, colourOf,
      { x: a[0], y: a[1], width: b[0] - a[0], height: b[1] - a[1] });
    image.setAttribute('data-layer', name);
    if ((b[0] - a[0]) / display.cols >= 3) image.setAttribute('style', 'image-rendering:pixelated');
    panel.layer.appendChild(image);
  }

  /* Contours of the land heights, by marching squares over the display's
   * heights thinned again to at most 300 cells a side, every `interval`
   * metres. Sea, assumed sea and gaps are left out, so a contour stops at
   * the coast and at a gap rather than running round a fill value. */
  function terrainContours(panel, display, geo, interval) {
    if (!(interval > 0)) return;
    var step = Math.max(1, Math.ceil(Math.max(display.rows, display.cols) / 300));
    var nx = Math.ceil(display.cols / step), ny = Math.ceil(display.rows / step), s = display.stride;
    var xs = [], ys = [], zs = [], lo = Infinity, hi = -Infinity, i, j;
    for (i = 0; i < nx; i++) xs.push(panel.project(geo.lon(geo.c0 + i * step * s), geo.south)[0]);
    for (j = 0; j < ny; j++) ys.push(panel.project(geo.west, geo.lat(geo.r0 + j * step * s))[1]);
    for (j = 0; j < ny; j++) {
      for (i = 0; i < nx; i++) {
        var k = j * step * display.cols + i * step, v = display.z[k];
        if (display.cls[k] !== 1 || v !== v) {
          zs.push(null);
          continue;
        }
        zs.push(v);
        if (v < lo) lo = v;
        if (v > hi) hi = v;
      }
    }
    if (!(hi >= lo)) return;
    var levels = [];
    for (var n = Math.ceil(lo / interval); n * interval <= hi && levels.length < 400; n++) {
      levels.push(n * interval);
    }
    contourLinePaths({ nx: nx, ny: ny, x: xs, y: ys, z: zs }, levels).forEach(function (segments) {
      if (!segments.length) return;
      var d = '';
      segments.forEach(function (seg) {
        d += 'M' + seg[0][0].toFixed(1) + ' ' + seg[0][1].toFixed(1) +
          'L' + seg[1][0].toFixed(1) + ' ' + seg[1][1].toFixed(1);
      });
      panel.layer.appendChild(svgEl('path', {
        d: d, fill: 'none', stroke: TERRAIN_CONTOUR, 'stroke-width': 0.5, 'stroke-opacity': 0.7,
        'data-contour': 'true',
      }));
    });
  }

  /* The drainage lines' parts, which the analysis cut to the square shown:
   * 0.6 px wide at Strahler order 1 and half a pixel wider for each order
   * above, as the caption says; dashed where the part drains ground beyond
   * the analysed square or behind a gap (edge_contaminated), so its area
   * and order may be larger or smaller than drawn; and each stretch routed
   * across a flat or a filled hollow rather than by slope (stretch_flat)
   * at 45% opacity, the least certain stretches drawn the palest. Each run
   * of stretches routed alike is a path of its own, so a dashed run takes
   * up the pattern where the run before it left off, and a short run is not
   * drawn solid by starting it again. A run routed by slope ends square, so
   * its ends do not cover a flat-routed run beside it; a flat-routed run
   * keeps round ends, which fall on the darker run and fill the outside of
   * the corner between them. A part's vertices are [row, column] of the
   * analysed grid. */
  function terrainDrainage(panel, parts, geo) {
    (parts || []).forEach(function (part) {
      var vertices = part.vertices || [];
      if (vertices.length < 2) return;
      var width = 0.6 + 0.5 * (part.strahler - 1);
      var flat = part.stretch_flat || [];
      var dash = part.edge_contaminated
        ? (2.6 * width + 1.4).toFixed(1) + ' ' + (1.6 * width + 0.9).toFixed(1) : null;
      var pts = vertices.map(function (v) { return panel.project(geo.lon(v[1]), geo.lat(v[0])); });
      var stretches = pts.length - 1, start = 0, along = 0;
      for (var s = 1; s <= stretches; s++) {
        if (s < stretches && !!flat[s] === !!flat[start]) continue;
        panel.layer.appendChild(polyline(pts.slice(start, s + 1), {
          stroke: TERRAIN_LINE, 'stroke-width': width, 'stroke-opacity': flat[start] ? 0.45 : null,
          'stroke-dasharray': dash, 'stroke-dashoffset': dash ? along.toFixed(2) : null,
          'stroke-linecap': dash || !flat[start] ? 'butt' : 'round', 'data-link': part.id,
        }));
        for (; start < s; start++) {
          along += Math.hypot(pts[start + 1][0] - pts[start][0], pts[start + 1][1] - pts[start][1]);
        }
      }
    });
  }

  /* The site, as _mark_site marks it on the topographic map: a red star
   * ringed in white, with its name beside it when it has one, drawn over
   * the panel's furniture. Left off a panel it does not fall in. */
  function terrainSite(svg, panel, site, p) {
    if (!site || !isFinite(site.lon) || !isFinite(site.lat)) return;
    var pt = panel.project(site.lon, site.lat), r = panel.rect;
    if (pt[0] < r.x || pt[0] > r.x + r.w || pt[1] < r.y || pt[1] > r.y + r.h) return;
    var mark = marker(pt[0], pt[1], 'star', TERRAIN_SITE, '#FFFFFF', 5);
    mark.setAttribute('data-site', 'true');
    svg.appendChild(mark);
    if (site.label) {
      svg.appendChild(svgEl('text', {
        x: pt[0] + 9, y: pt[1] - 7, 'font-size': 9, 'font-weight': 700, fill: TERRAIN_SITE,
        stroke: p.surface, 'stroke-width': 2.6, 'paint-order': 'stroke', text: site.label,
      }));
    }
  }

  /* One terrain figure: its title; its panels, `columns` across, each a
   * map of the square shown with a graticule, a neatline, a scale bar and
   * a north arrow; a colour bar beside them when the figure has one; and
   * the credit and the caveat under them. Each panel is {name, title,
   * colourOf, overlay}: colourOf colours the display's cells (rasterImage),
   * and overlay(panel, geo) draws over the raster, inside the panel's clip
   * and under its furniture. `bar` is colourBar's spec without its place,
   * or null; `legend` is legend's entries, drawn in the first panel's upper
   * left, or none; and `caveat`, where given, is drawn in place of the
   * captions' figure_caveat. */
  function terrainFigure(display, opts, spec) {
    var p = palette();
    var width = opts.width || 680;
    var geo = terrainGeometry(display);
    var panels = spec.panels, columns = Math.min(spec.columns || 1, panels.length);
    var rowsOfPanels = Math.ceil(panels.length / columns);
    /* the maps are drawn on projectionInto's equirectangular scale, so
     * each box takes the shape that projection gives the square shown */
    var kx = Math.cos((geo.south + geo.north) / 2 * Math.PI / 180);
    var aspect = (geo.north - geo.south) / Math.max((geo.east - geo.west) * kx, 1e-12);
    var left = 54, gap = 58, right = spec.bar ? 104 : 18;
    var pw = (width - left - right - gap * (columns - 1)) / columns;
    var ph = pw * aspect;
    if (ph > pw * 1.3) {
      ph = pw * 1.3;
      pw = ph / aspect;
    }
    var spread = width - left - right - gap * (columns - 1) - pw * columns;
    /* graticuleStep's three to six lines across, but none closer than about
     * 90 px, which is what a label in degrees and minutes takes: the panels
     * drawn two across, given the step of a map twice their width, printed
     * their numbers into one another */
    var step = graticuleStep(Math.max(geo.east - geo.west, geo.north - geo.south) * 3.5 /
      Math.max(2, Math.min(3.5, pw / 90)));
    var titled = panels.some(function (panel) { return !!panel.title; }) ? 17 : 0;
    var titleLines = spec.title
      ? wrapText(spec.title, width - left - 14, TITLE_SIZE * TITLE_BOLD_WIDTH) : [];
    var top = 14 + titleLines.length * 16;
    /* a row of panels, the graticule's numbers under it and a gap */
    var rowStep = titled + ph + 24;

    var notes = [], notesWidth = width - left - 14;
    if (opts.figureCredit) {
      wrapText(opts.figureCredit, notesWidth, 8.5).forEach(function (line) {
        notes.push({ text: line, fill: p.muted, note: 'credit' });
      });
    }
    var caveat = spec.caveat !== undefined ? spec.caveat : opts.captions && opts.captions.figure_caveat;
    if (caveat) {
      wrapText(caveat, notesWidth, 8.5).forEach(function (line) {
        notes.push({ text: line, fill: p.inkSoft, note: 'caveat' });
      });
    }
    var notesTop = top + rowsOfPanels * rowStep + 6;
    var height = Math.ceil(notesTop + notes.length * 11 + 6);

    var svg = svgEl('svg', {
      viewBox: '0 0 ' + width + ' ' + height, width: '100%', xmlns: NS, 'font-family': FONT,
      role: 'img', 'aria-label': spec.title || 'Terrain figure',
    });
    svg.appendChild(svgEl('rect', { x: 0, y: 0, width: width, height: height, fill: p.surface }));
    titleLines.forEach(function (line, i) {
      svg.appendChild(svgEl('text', {
        x: left, y: 18 + i * 16, 'font-size': TITLE_SIZE, 'font-weight': 600, fill: p.ink, text: line,
      }));
    });

    var extent = [{ geometry: { type: 'Polygon', coordinates: [[[geo.west, geo.south], [geo.east, geo.south],
      [geo.east, geo.north], [geo.west, geo.north], [geo.west, geo.south]]] } }];
    var rects = panels.map(function (entry, i) {
      var rect = {
        x: left + spread / 2 + (i % columns) * (pw + gap),
        y: top + Math.floor(i / columns) * rowStep + titled, w: pw, h: ph,
      };
      if (entry.title) {
        svg.appendChild(svgEl('text', {
          x: rect.x, y: rect.y - 5, 'font-size': 11, 'font-weight': 600, fill: p.inkSoft,
          text: entry.title,
        }));
      }
      clipSeq += 1;
      var clipId = 'gwt-clip-' + clipSeq;
      svg.appendChild(svgEl('defs', null, [svgEl('clipPath', { id: clipId }, [svgEl('rect', {
        x: rect.x, y: rect.y, width: rect.w, height: rect.h,
      })])]));
      var panel = {
        rect: rect, project: projectionInto(extent, rect, 0),
        layer: svgEl('g', { 'clip-path': 'url(#' + clipId + ')' }),
      };
      svg.appendChild(panel.layer);
      terrainRaster(panel, display, geo, entry.colourOf, entry.name);
      if (entry.overlay) entry.overlay(panel, geo);
      drawMapFurniture(svg, panel.project, rect, p, { step: step });
      terrainSite(svg, panel, opts.site, p);
      return rect;
    });

    /* a key in the first panel's upper left, which the scale bar (lower
     * left) and the north arrow (upper right) leave free */
    if (spec.legend) {
      legend({ svg: svg, palette: p }, spec.legend, { x: rects[0].x + 14, y: rects[0].y + 20 });
    }
    if (spec.bar) {
      var barTop = rects[0].y + ph * 0.075, barBottom = rects[rects.length - 1].y + ph * 0.925;
      var edge = rects[columns - 1];
      colourBar({ svg: svg, palette: p }, Object.assign({
        x: edge.x + edge.w + 12, top: barTop, height: barBottom - barTop, linear: true,
      }, spec.bar));
    }
    notes.forEach(function (line, i) {
      svg.appendChild(svgEl('text', {
        x: left, y: notesTop + 8 + i * 11, 'font-size': 8.5, fill: line.fill,
        'data-note': line.note, text: line.text,
      }));
    });
    return svg;
  }

  /**
   * What the four terrain figures take besides the display layers: only
   * what the analysis and the read worked out, never anything a figure
   * could work out for itself.
   * @typedef {Object} TerrainFigureOptions
   * @property {Array<Object>} [parts] the drainage lines' parts in the square shown, as
   *   C.drainageLinks gives them (terrainRelief draws them)
   * @property {Object} summary the analysis's summary: contour_interval (terrainRelief), twi_range
   *   (wetnessMap) and curvature_limit (curvatureMaps)
   * @property {Object<string, string>} captions what C.terrainCaptions gives: the title_ keys, the
   *   panel_ keys (hillshadeDirections) and figure_caveat, drawn inside every figure
   * @property {{lon: number, lat: number, label?: string}|null} [site] the site, starred where it
   *   falls in the square shown, with its label beside the star when it has one
   * @property {string|null} [figureCredit] the elevation model's credit line, as the read's
   *   figureCredit gives it, drawn inside every figure above the caveat
   * @property {Object|null} [cfg] the configuration's terrain section; hillshadeDirections names its
   *   panels' layers by hillshade_panel_azimuths_deg
   * @property {Object|null} [lineaments] what C.lineamentCandidates gives (lineamentMap and
   *   lineamentRose), whose captions, C.lineamentCaptions's, are merged into `captions`
   * @property {{lons: ArrayLike<number>, lats: ArrayLike<number>}|null} [axes] the analysed grid's
   *   cell centres, which lineamentMap places the candidates' ends by (C.lineamentLonLat)
   * @property {Object|null} [plan] what C.surveyPlan gives (surveyPlanMap), whose captions,
   *   C.surveyPlanCaptions's, are merged into `captions` with the candidates'
   * @property {number} [width] the figure's width in the SVG's units, 680 by default
   */

  /**
   * The first terrain figure: shaded relief and the drainage lines, cropped
   * to the square shown. Land is matplotlib's terrain ramp without its
   * bathymetry (terrain_land) over the land heights shown, blended 35% with
   * the multidirectional hillshade in grey, (1 - 0.35) terrain_land(z) +
   * 0.35 grey(multi); ground the fill raised is tinted at 0.25. Over it,
   * the contours at the summary's interval, and the drainage lines as
   * terrainDrainage draws them. Sea, hatched assumed sea and gaps as every
   * terrain panel draws them.
   * @param {Object|null} display what C.terrainDisplayLayers gives
   * @param {TerrainFigureOptions} opts
   * @returns {SVGElement|null} the figure, or null without a display
   */
  function terrainRelief(display, opts) {
    if (!display) return null;
    var o = /** @type {TerrainFigureOptions} */ (opts || {});
    var summary = o.summary || {}, captions = o.captions || {};
    var z = display.z, cls = display.cls, multi = display.hillshadeMulti, raised = display.raised;
    var lo = Infinity, hi = -Infinity;
    for (var k = 0; k < cls.length; k++) {
      if (cls[k] !== 1 || z[k] !== z[k]) continue;
      if (z[k] < lo) lo = z[k];
      if (z[k] > hi) hi = z[k];
    }
    var land = rampTable('terrain_land');
    return terrainFigure(display, o, {
      title: captions.title_relief,
      panels: [{
        name: 'relief',
        colourOf: function (value, k, x, y) {
          var ground = terrainGround(display, k, x, y);
          if (ground !== -2) return ground;
          var c = land[rampEntry(z[k], lo, hi)], shade = multi[k];
          /* hillshade is NaN on the edge and beside a gap, where the
           * height is drawn unshaded, as matplotlib leaves a NaN out */
          if (shade === shade) c = mixPacked(c, rampEntry(shade, 0, 1) * 0x010101, 0.35);
          return raised[k] ? mixPacked(c, TERRAIN_FILL_TINT, 0.25) : c;
        },
        overlay: function (panel, geo) {
          terrainContours(panel, display, geo, summary.contour_interval);
          terrainDrainage(panel, o.parts, geo);
        },
      }],
      bar: hi > lo ? { range: [lo, hi], ramp: 'terrain_land', label: 'Ground elevation (m)' } : null,
    });
  }

  /**
   * The second terrain figure: the topographic wetness index on GnBu over
   * the summary's twi_range, cropped to the square shown. Cells flagged as
   * receiving water from beyond the analysed square or from behind a gap
   * are blended 35% with white, as the caption says, because their values
   * are uncertain. Where the index is NaN on land (the edge of the
   * analysis, beside a gap) the cell is left blank.
   * @param {Object|null} display what C.terrainDisplayLayers gives
   * @param {TerrainFigureOptions} opts
   * @returns {SVGElement|null} the figure, or null without a display
   */
  function wetnessMap(display, opts) {
    if (!display) return null;
    var o = /** @type {TerrainFigureOptions} */ (opts || {});
    var summary = o.summary || {}, captions = o.captions || {};
    var range = summary.twi_range || [NaN, NaN], lo = range[0], hi = range[1];
    var twi = display.twi, flag = display.flag, gnbu = rampTable('GnBu');
    return terrainFigure(display, o, {
      title: captions.title_wetness,
      panels: [{
        name: 'wetness',
        colourOf: function (value, k, x, y) {
          var ground = terrainGround(display, k, x, y);
          if (ground !== -2) return ground;
          var v = twi[k];
          if (v !== v) return -1;
          var c = gnbu[rampEntry(v, lo, hi)];
          return flag[k] ? mixPacked(c, 0xFFFFFF, 0.35) : c;
        },
      }],
      bar: hi > lo ? { range: [lo, hi], ramp: 'GnBu', label: 'Wetness index' } : null,
    });
  }

  /**
   * The third terrain figure: profile curvature (down the slope) and
   * tangential curvature (across it) side by side, per km, on BrBG
   * reversed over one symmetric limit, the summary's curvature_limit, so
   * that the two panels can be compared colour for colour: brown where the
   * ground is convex or spreads water, blue-green where it is concave or
   * gathers it. Ground flatter than the floor has no curvature and is left
   * blank, as the caption says.
   * @param {Object|null} display what C.terrainDisplayLayers gives
   * @param {TerrainFigureOptions} opts
   * @returns {SVGElement|null} the figure, or null without a display
   */
  function curvatureMaps(display, opts) {
    if (!display) return null;
    var o = /** @type {TerrainFigureOptions} */ (opts || {});
    var summary = o.summary || {}, captions = o.captions || {};
    var limit = Number(summary.curvature_limit) * 1000, scale = limit > 0 ? limit : 1;
    var brbg = rampTable('BrBG_r');
    function panel(name, title, layer) {
      return {
        name: name, title: title,
        colourOf: function (value, k, x, y) {
          var ground = terrainGround(display, k, x, y);
          if (ground !== -2) return ground;
          var v = layer[k];
          return v === v ? brbg[rampEntry(v * 1000, -scale, scale)] : -1;
        },
      };
    }
    return terrainFigure(display, o, {
      title: captions.title_curvature, columns: 2,
      panels: [panel('profile', 'Down the slope (profile)', display.profile),
        panel('tangential', 'Across the slope (tangential)', display.tangential)],
      bar: limit > 0 ? { range: [-limit, limit], ramp: 'BrBG_r', label: 'Curvature (per km)' } : null,
    });
  }

  /**
   * The fourth terrain figure: the relief lit from each panel azimuth in
   * turn (270, 315, 0 and 45 degrees by default, all from above), two
   * panels across, each titled with the engine's panel_ caption, in grey
   * from 0 (in shadow) to 1 (facing the light). A straight feature shows
   * most under light across it, which is what the panels are for.
   * @param {Object|null} display what C.terrainDisplayLayers gives
   * @param {TerrainFigureOptions} opts
   * @returns {SVGElement|null} the figure, or null without a display or panels
   */
  function hillshadeDirections(display, opts) {
    if (!display || !display.hillshades || !display.hillshades.length) return null;
    var o = /** @type {TerrainFigureOptions} */ (opts || {});
    var captions = o.captions || {}, grey = rampTable('gray');
    var azimuths = (o.cfg && o.cfg.hillshade_panel_azimuths_deg) || [];
    return terrainFigure(display, o, {
      title: captions.title_directions, columns: 2,
      panels: display.hillshades.map(function (layer, t) {
        return {
          name: 'hillshade-' + (azimuths[t] === undefined ? t : azimuths[t]),
          title: captions['panel_' + t] || '',
          colourOf: function (value, k, x, y) {
            var ground = terrainGround(display, k, x, y);
            if (ground !== -2) return ground;
            var v = layer[k];
            return v === v ? grey[rampEntry(v, 0, 1)] : -1;
          },
        };
      }),
      bar: null,
    });
  }

  /* What both lineament figures draw under their credit, as one paragraph:
   * that the candidates are inferred from terrain, then the caveat
   * (terrain._lineament_note). */
  function lineamentNote(captions) {
    return [captions.figure_note, captions.figure_caveat].filter(Boolean).join(' ');
  }

  /**
   * The fifth terrain figure (PLAN.md step 4.2): the lineament candidates
   * over the relief of the square shown, as mapping/terrain.py's
   * plot_lineaments draws them. The land is the multidirectional hillshade
   * in grey, lightened 40% towards white; sea, hatched assumed sea and gaps
   * as every terrain panel draws them. Each candidate is a straight line
   * from its start to its end, placed by C.lineamentLonLat on the analysed
   * grid's cell centres, a valley blue and a ridge orange, keyed in the
   * upper left. The note that the candidates are inferred from terrain is
   * drawn with the caveat under the credit.
   * @param {Object|null} display what C.terrainDisplayLayers gives
   * @param {TerrainFigureOptions} opts with `lineaments` and `axes`
   * @returns {SVGElement|null} the figure, or null without a display or candidates' analysis
   */
  function lineamentMap(display, opts) {
    var o = /** @type {TerrainFigureOptions} */ (opts || {});
    if (!display || !o.lineaments || !o.axes) return null;
    var captions = o.captions || {}, grey = rampTable('gray'), multi = display.hillshadeMulti;
    var result = o.lineaments, axes = o.axes;
    var segments = result.lineaments.map(function (item) {
      return { id: item.id, kind: item.kind, a: C.lineamentLonLat(result, axes.lons, axes.lats, item.start),
        b: C.lineamentLonLat(result, axes.lons, axes.lats, item.end) };
    });
    return terrainFigure(display, o, {
      title: captions.title_lineaments,
      caveat: lineamentNote(captions),
      panels: [{
        name: 'lineaments',
        colourOf: function (value, k, x, y) {
          var ground = terrainGround(display, k, x, y);
          if (ground !== -2) return ground;
          var v = multi[k];
          return v === v ? mixPacked(grey[rampEntry(v, 0, 1)], 0xFFFFFF, LINEAMENT_GROUND) : -1;
        },
        overlay: function (panel) {
          segments.forEach(function (seg) {
            var a = panel.project(seg.a[0], seg.a[1]), b = panel.project(seg.b[0], seg.b[1]);
            panel.layer.appendChild(svgEl('line', {
              x1: a[0], y1: a[1], x2: b[0], y2: b[1], 'stroke-width': LINEAMENT_WIDTH, 'stroke-linecap': 'round',
              stroke: seg.kind === 'valley' ? LINEAMENT_VALLEY : LINEAMENT_RIDGE,
              'data-lineament': seg.id, 'data-kind': seg.kind,
            }));
          });
        },
      }],
      legend: [{ kind: 'line', colour: LINEAMENT_VALLEY, label: 'Straight valley' },
        { kind: 'line', colour: LINEAMENT_RIDGE, label: 'Straight ridge' }],
      bar: null,
    });
  }

  /* A ring's length: in km to a tenth below 10 km and whole above
   * (terrain._rose_label). */
  function roseLabel(metres) {
    var km = metres / 1000;
    return C.pyFixed(km, km < 10 ? 1 : 0) + ' km';
  }

  /**
   * The sixth terrain figure (PLAN.md step 4.2): the strikes of the
   * lineament candidates as two roses, valleys and ridges side by side, as
   * plot_lineament_rose draws them. Each 10-degree band is a petal drawn
   * twice, opposite itself, north up and bearings clockwise; a petal
   * reaches the square root of its band's length over the longest band's,
   * of either rose, so its area goes with the length and the two roses are
   * on one scale. The rings are at a quarter, a half, three quarters and
   * all of the longest band's length, named along the bearing 22.5°. Each
   * rose is headed with its count and length (rose_valleys, rose_ridges),
   * and the credit and the note are drawn under both.
   * @param {Object|null} result what C.lineamentCandidates gives
   * @param {TerrainFigureOptions} opts its captions merged with C.lineamentCaptions's
   * @returns {SVGElement|null} the figure, or null where there is no candidate to draw
   */
  function lineamentRose(result, opts) {
    if (!result) return null;
    var o = /** @type {TerrainFigureOptions} */ (opts || {});
    var captions = o.captions || {}, p = palette(), width = o.width || 680;
    var longest = Math.max.apply(null, result.roseValleyM.concat(result.roseRidgeM));
    if (!(longest > 0)) return null;
    var left = 54, right = 18, gap = 58;
    var side = (width - left - right - gap) / 2, radius = side / 2 - 26;
    var titleLines = captions.title_rose ? wrapText(captions.title_rose, width - left - 14,
      TITLE_SIZE * TITLE_BOLD_WIDTH) : [];
    var top = 14 + titleLines.length * 16 + 24;
    var notes = [], notesWidth = width - left - 14;
    if (o.figureCredit) {
      wrapText(o.figureCredit, notesWidth, 8.5).forEach(function (line) {
        notes.push({ text: line, fill: p.muted, note: 'credit' });
      });
    }
    var note = lineamentNote(captions);
    if (note) {
      wrapText(note, notesWidth, 8.5).forEach(function (line) {
        notes.push({ text: line, fill: p.inkSoft, note: 'caveat' });
      });
    }
    var notesTop = top + side + 10;
    var height = Math.ceil(notesTop + notes.length * 11 + 6);
    var svg = svgEl('svg', {
      viewBox: '0 0 ' + width + ' ' + height, width: '100%', xmlns: NS, 'font-family': FONT,
      role: 'img', 'aria-label': captions.title_rose || 'Rose of strikes',
    });
    svg.appendChild(svgEl('rect', { x: 0, y: 0, width: width, height: height, fill: p.surface }));
    titleLines.forEach(function (line, i) {
      svg.appendChild(svgEl('text', {
        x: left, y: 18 + i * 16, 'font-size': TITLE_SIZE, 'font-weight': 600, fill: p.ink, text: line,
      }));
    });
    var at = function (cx, cy, reach, degrees) {
      var a = degrees * Math.PI / 180;
      return [cx + reach * Math.sin(a), cy - reach * Math.cos(a)];
    };
    [['valley', result.roseValleyM, LINEAMENT_VALLEY, captions.rose_valleys],
      ['ridge', result.roseRidgeM, LINEAMENT_RIDGE, captions.rose_ridges]].forEach(function (rose, n) {
      var kind = rose[0], lengths = rose[1], colour = rose[2], heading = rose[3];
      var cx = left + n * (side + gap) + side / 2, cy = top + side / 2;
      if (heading) {
        svg.appendChild(svgEl('text', {
          x: cx, y: top - 8, 'text-anchor': 'middle', 'font-size': 11, 'font-weight': 600, fill: p.inkSoft,
          text: heading,
        }));
      }
      var g = svgEl('g', { 'data-rose': kind });
      svg.appendChild(g);
      lengths.forEach(function (length, band) {
        if (!(length > 0)) return;
        var reach = Math.sqrt(length / longest) * radius;
        [band * 10, band * 10 + 180].forEach(function (start) {
          var a = at(cx, cy, reach, start), b = at(cx, cy, reach, start + 10);
          g.appendChild(svgEl('path', {
            d: 'M' + cx.toFixed(2) + ' ' + cy.toFixed(2) + 'L' + a[0].toFixed(2) + ' ' + a[1].toFixed(2) +
              'A' + reach.toFixed(2) + ' ' + reach.toFixed(2) + ' 0 0 1 ' + b[0].toFixed(2) + ' ' +
              b[1].toFixed(2) + 'Z',
            fill: colour, 'fill-opacity': PETAL_OPACITY, stroke: '#FFFFFF', 'stroke-width': 0.5,
            'data-petal': kind, 'data-band': band, 'data-from': start,
            'data-reach': (reach / radius).toFixed(6),
          }));
        });
      });
      /* the rings and the bearings over the petals, the rings named */
      ROSE_RINGS.forEach(function (share) {
        var reach = Math.sqrt(share) * radius;
        svg.appendChild(svgEl('circle', {
          cx: cx, cy: cy, r: reach, fill: 'none', stroke: p.muted,
          'stroke-width': share === 1 ? 1 : 0.4, 'stroke-opacity': share === 1 ? 0.9 : 0.6,
        }));
        var spot = at(cx, cy, reach, 22.5);
        svg.appendChild(svgEl('text', {
          x: spot[0] + 2, y: spot[1] - 2, 'font-size': 8, fill: p.inkSoft, stroke: p.surface,
          'stroke-width': 2.4, 'paint-order': 'stroke', 'data-ring': share, text: roseLabel(share * longest),
        }));
      });
      [[0, 'N'], [90, 'E'], [180, 'S'], [270, 'W']].forEach(function (mark) {
        var a = at(cx, cy, radius, mark[0]), b = at(cx, cy, radius + 13, mark[0]);
        svg.appendChild(svgEl('line', {
          x1: cx, y1: cy, x2: a[0], y2: a[1], stroke: p.muted, 'stroke-width': 0.4, 'stroke-opacity': 0.6,
        }));
        svg.appendChild(svgEl('text', {
          x: b[0], y: b[1] + 4, 'text-anchor': 'middle', 'font-size': 10, fill: p.inkSoft, text: mark[1],
        }));
      });
    });
    notes.forEach(function (line, i) {
      svg.appendChild(svgEl('text', {
        x: left, y: notesTop + 8 + i * 11, 'font-size': 8.5, fill: line.fill,
        'data-note': line.note, text: line.text,
      }));
    });
    return svg;
  }

  /* The survey plan's figure (mapping/terrain.py plot_survey_plan): the
   * profiling lines in purple, apart from the candidates' blue and orange;
   * the separation rings thin, dashed and brown; the service radius dashed
   * in near-black; the mapped water points in a survey point's blue; and
   * the view's half side, in service radii. */
  var PLAN_LINE = '#5B2A86';
  var PLAN_RING = '#8A5A2B';
  var PLAN_RADIUS = '#333333';
  var PLAN_WATER = '#17527E';
  var PLAN_VIEW = 1.25;

  /* The display layers a figure of part of the square shown draws: rows
   * r0 to r1 and columns c0 to c1 of the analysed grid (half-open), cut to
   * the square shown, in whole display cells. terrainGeometry places it as
   * it places the whole. */
  function cropDisplay(display, r0, r1, c0, c1) {
    var s = display.stride, shown = display.shown;
    var y0 = Math.max(0, Math.floor((r0 - shown[0]) / s)), y1 = Math.min(display.rows, Math.ceil((r1 - shown[0]) / s));
    var x0 = Math.max(0, Math.floor((c0 - shown[2]) / s)), x1 = Math.min(display.cols, Math.ceil((c1 - shown[2]) / s));
    if (!(y1 > y0 && x1 > x0)) return null;
    var rows = y1 - y0, cols = x1 - x0;
    var pick = function (layer, Kind) {
      var out = new Kind(rows * cols);
      for (var y = 0; y < rows; y++) {
        for (var x = 0; x < cols; x++) out[y * cols + x] = layer[(y0 + y) * display.cols + x0 + x];
      }
      return out;
    };
    return {
      rows: rows, cols: cols, stride: s, lons: display.lons.slice(x0, x1), lats: display.lats.slice(y0, y1),
      shown: [shown[0] + y0 * s, Math.min(shown[1], shown[0] + y1 * s), shown[2] + x0 * s,
        Math.min(shown[3], shown[2] + x1 * s)],
      cls: pick(display.cls, Uint8Array), assumedSea: pick(display.assumedSea, Uint8Array),
      hillshadeMulti: pick(display.hillshadeMulti, Float32Array),
    };
  }

  /* a circle of d metres round [x, y] of the candidates' frame, in
   * longitude and latitude, closed, from the vertices the plan's GeoJSON
   * writes */
  function planRing(plan, axes, x, y, d) {
    var points = [];
    for (var k = 0; k <= 64; k++) {
      var sc = C.sinCosDeg(360 * (k % 64) / 64);
      points.push(C.lineamentLonLat(plan, axes.lons, axes.lats, [x + d * sc[0], y + d * sc[1]]));
    }
    return points;
  }

  /**
   * The seventh terrain figure (PLAN.md step 4.3): the survey plan round
   * the site, as mapping/terrain.py's plot_survey_plan draws it. The ground
   * is the lineament map's, the multidirectional hillshade in grey
   * lightened towards white, cut to a square a quarter wider than the
   * service radius each way, with the drainage lines as the relief draws
   * them and the candidates as the lineament map draws them. Over those:
   * the service radius, dashed; each mapped water point within reach with
   * its separation ring; each profiling line with a dot at each station
   * and its name at its start; and each proposed sounding as a numbered
   * ring, its spread dashed along its candidate's strike to the AB/2 it is
   * planned to. The note that the candidates are inferred from terrain and
   * the pegs are proposals is drawn with the caveat under the credit.
   * @param {Object|null} display what C.terrainDisplayLayers gives
   * @param {TerrainFigureOptions} opts with `plan`, `lineaments` and `axes`
   * @returns {SVGElement|null} the figure, or null without a display, a plan or a line
   */
  function surveyPlanMap(display, opts) {
    var o = /** @type {TerrainFigureOptions} */ (opts || {});
    var plan = o.plan, result = o.lineaments, axes = o.axes;
    if (!display || !plan || !plan.lines.length || !result || !axes) return null;
    var captions = o.captions || {}, grey = rampTable('gray');
    var dx = plan.frame[0], dy = plan.frame[1], sx = plan.site[0], sy = plan.site[1];
    var half = PLAN_VIEW * plan.radius_m;
    var r0 = Math.floor((sy - half) / dy), r1 = Math.ceil((sy + half) / dy) + 1;
    var c0 = Math.floor((sx - half) / dx), c1 = Math.ceil((sx + half) / dx) + 1;
    var crop = cropDisplay(display, r0, r1, c0, c1);
    if (!crop) return null;
    var multi = crop.hillshadeMulti, reach = Number(plan.ab2.max_ab2);
    var at = function (point) { return C.lineamentLonLat(plan, axes.lons, axes.lats, point); };
    var parts = (o.parts || []).filter(function (part) {
      return part.vertices.some(function (v) { return v[0] >= r0 && v[0] < r1 && v[1] >= c0 && v[1] < c1; });
    });
    var segments = result.lineaments.map(function (item) {
      return { id: item.id, kind: item.kind, a: C.lineamentLonLat(result, axes.lons, axes.lats, item.start),
        b: C.lineamentLonLat(result, axes.lons, axes.lats, item.end) };
    });
    var path = function (panel, points, attrs) {
      return polyline(points.map(function (p) { return panel.project(p[0], p[1]); }), attrs);
    };
    return terrainFigure(crop, o, {
      title: captions.title_plan,
      caveat: [captions.plan_note, captions.figure_caveat].filter(Boolean).join(' '),
      panels: [{
        name: 'plan',
        colourOf: function (value, k, x, y) {
          var ground = terrainGround(crop, k, x, y);
          if (ground !== -2) return ground;
          var v = multi[k];
          return v === v ? mixPacked(grey[rampEntry(v, 0, 1)], 0xFFFFFF, LINEAMENT_GROUND) : -1;
        },
        overlay: function (panel, geo) {
          var layer = panel.layer;
          terrainDrainage(panel, parts, geo);
          segments.forEach(function (seg) {
            var a = panel.project(seg.a[0], seg.a[1]), b = panel.project(seg.b[0], seg.b[1]);
            layer.appendChild(svgEl('line', {
              x1: a[0], y1: a[1], x2: b[0], y2: b[1], 'stroke-width': LINEAMENT_WIDTH, 'stroke-linecap': 'round',
              stroke: seg.kind === 'valley' ? LINEAMENT_VALLEY : LINEAMENT_RIDGE,
              'data-lineament': seg.id, 'data-kind': seg.kind,
            }));
          });
          layer.appendChild(path(panel, planRing(plan, axes, sx, sy, plan.radius_m), {
            stroke: PLAN_RADIUS, 'stroke-width': 1.2, 'stroke-dasharray': '5 3', 'data-radius': plan.radius_m,
          }));
          plan.rings.forEach(function (ring) {
            layer.appendChild(path(panel, planRing(plan, axes, ring[0], ring[1], ring[3]), {
              stroke: PLAN_RING, 'stroke-width': 0.9, 'stroke-dasharray': '2 2', 'data-ring': ring[2],
              'data-distance': ring[3],
            }));
            var w = at([ring[0], ring[1]]), q = panel.project(w[0], w[1]);
            layer.appendChild(marker(q[0], q[1], 'square', PLAN_WATER, '#FFFFFF', 3.2));
          });
          plan.lines.forEach(function (line) {
            var points = [];
            for (var k = line.first; k <= line.last; k++) {
              var p = at(C.lineStation(line, k));
              points.push(panel.project(p[0], p[1]));
            }
            var ends = [points[0], points[points.length - 1]];
            layer.appendChild(polyline(ends, {
              stroke: PLAN_LINE, 'stroke-width': 2.4, 'stroke-linecap': 'butt', 'data-plan-line': line.id,
            }));
            points.forEach(function (pt) {
              layer.appendChild(svgEl('circle', { cx: pt[0], cy: pt[1], r: 1.1, fill: PLAN_LINE, 'data-station': line.id }));
            });
            var east = line.direction[0] >= 0;
            layer.appendChild(svgEl('text', {
              x: points[0][0] + (east ? -6 : 6), y: points[0][1] + 3, 'text-anchor': east ? 'end' : 'start',
              'font-size': 9, 'font-weight': 700, fill: PLAN_LINE, stroke: '#FFFFFF', 'stroke-width': 2.6,
              'paint-order': 'stroke', text: C.phrase('survey_plan.line_name', { line: line.id }),
            }));
          });
          plan.soundings.forEach(function (x) {
            var sc = C.sinCosDeg(x.spread_deg);
            var a = at([x.point[0] - reach * sc[0], x.point[1] - reach * sc[1]]);
            var b = at([x.point[0] + reach * sc[0], x.point[1] + reach * sc[1]]);
            layer.appendChild(polyline([panel.project(a[0], a[1]), panel.project(b[0], b[1])], {
              stroke: PLAN_LINE, 'stroke-width': 0.8, 'stroke-dasharray': '3 2', 'stroke-opacity': 0.75,
              'data-spread': x.id,
            }));
          });
          plan.soundings.forEach(function (x) {
            var w = at(x.point), q = panel.project(w[0], w[1]);
            layer.appendChild(svgEl('circle', {
              cx: q[0], cy: q[1], r: 7, fill: '#FFFFFF', stroke: PLAN_LINE, 'stroke-width': 1.6, 'data-sounding': x.id,
              'data-role': x.role,
            }));
            layer.appendChild(svgEl('text', {
              x: q[0], y: q[1] + 3.2, 'text-anchor': 'middle', 'font-size': 8.5, 'font-weight': 700, fill: PLAN_LINE,
              text: String(x.id),
            }));
          });
        },
      }],
      legend: [{ kind: 'line', colour: LINEAMENT_VALLEY, label: 'Straight valley' },
        { kind: 'line', colour: LINEAMENT_RIDGE, label: 'Straight ridge' },
        { kind: 'line', colour: PLAN_LINE, label: 'Profiling line' },
        { kind: 'circle', colour: PLAN_LINE, label: 'Proposed sounding' },
        { kind: 'line', colour: PLAN_RING, dash: '2 2', label: 'Separation ring' },
        { kind: 'line', colour: PLAN_RADIUS, dash: '5 3', label: 'Service radius' }],
      bar: null,
    });
  }

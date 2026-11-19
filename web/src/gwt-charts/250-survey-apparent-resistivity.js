
  /* -------------------------------------- the apparent-resistivity section */

  /* Sutherland-Hodgman against a linear field: the part of a convex polygon
   * where the interpolated value is above (or below) `level`.
   *
   * A triangle's value varies linearly across it, so a level cuts it along a
   * straight line and each clip leaves a convex polygon. Two clips give the
   * band between two levels exactly, which is what tricontourf fills - not an
   * approximation of it. Vertices carry {x, y, value}. */
  function clipPolygonByValue(poly, keepAbove, level) {
    var out = [], i;
    for (i = 0; i < poly.length; i += 1) {
      var a = poly[i], b = poly[(i + 1) % poly.length];
      var inA = keepAbove ? a[2] >= level : a[2] <= level;
      var inB = keepAbove ? b[2] >= level : b[2] <= level;
      if (inA) out.push(a);
      if (inA !== inB && b[2] !== a[2]) {
        var t = (level - a[2]) / (b[2] - a[2]);
        out.push([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, level]);
      }
    }
    return out;
  }

  /* mapping/subsurface.py apparent_resistivity_pseudosection: the readings
   * themselves laid out along the traverse, before any inversion has been
   * believed. The vertical axis is AB/2 - the electrode half-spacing - and is
   * labelled as such rather than converted to a depth, because the
   * pseudo-depth conversions vary with the very layering the figure is drawn
   * to reveal, and calling a measurement geometry a depth is how a
   * pseudo-section starts being read as a cross-section.
   *
   * `geometry` is what C.pseudosectionGeometry returned: the triangles it
   * hands over already have any pair of stations too far apart to correlate
   * left out, so no colour is drawn across ground nothing was measured on. */
  function apparentPseudosection(geometry, options) {
    if (!geometry || geometry.reason) return null;
    var opts = options || {};
    var xs = geometry.readings.x;
    var logY = geometry.readings.log_ab2;
    var rho = geometry.readings.rho;
    var levels = geometry.levels || [];
    var range = geometry.range || [1, 10];
    if (!xs.length || levels.length < 2) return null;

    var width = opts.width || 760;
    var noteLines = geometry.note ? wrapText(geometry.note, width - 150, 8.5) : [];
    var base = Math.round(width * 3.4 / FIGURE_WIDTH_IN);
    var height = (opts.height || base) + noteLines.length * 11 + 14;
    var ticks = (geometry.ticks || []).map(function (tick) {
      return { value: tick[0], label: tick[1] };
    });
    /* A filled contour pins its own axes to the data - matplotlib calls them
     * sticky edges - so the Python section runs edge to edge with no margin,
     * and the decade ticks then widen the vertical axis to whichever decades
     * it labels. Padding the browser's axes instead would leave a strip of
     * blank paper at each end of a section drawn to the same readings, which
     * reads as ground the survey covered and measured nothing on. With no
     * triangles to fill there is no contour and the ordinary 5% margin is
     * what matplotlib gives the readings. */
    var filled = (geometry.triangles || []).length > 0;
    var yValues = logY.concat(ticks.map(function (tick) { return tick.value; }));
    /* the top margin holds the station names as well as the title, one line
     * each, as the Python lifts its title clear of them: with room for the
     * title alone the names were written into it */
    var f = frame({
      width: width, height: height,
      margin: { top: 46, right: 104, bottom: 46 + noteLines.length * 11, left: 62 },
      title: opts.title || geometry.title,
      yLabel: geometry.y_label, yDown: true,
      xDomain: filled ? [Math.min.apply(null, xs), Math.max.apply(null, xs)]
        : padDomain(xs, false, 0.05),
      yDomain: filled ? [Math.min.apply(null, yValues), Math.max.apply(null, yValues)]
        : padDomain(yValues, false, 0.05),
      yTicks: ticks,
    });
    axisLabelBelow(f, geometry.x_label);
    var p = f.palette;
    var logLo = Math.log(range[0]), logHi = Math.log(range[1]);
    function colourFor(value) {
      return rampColour('viridis',
        logHi > logLo ? (Math.log(value) - logLo) / (logHi - logLo) : 0);
    }

    /* The banded fill between the readings. The two end bands are the ramp's
     * own ends rather than a midpoint, which is what extend="both" paints a
     * reading outside the level range: the colour says "off the scale", and a
     * midpoint colour would say it was an ordinary value. */
    /* One translucent group - `opacity`, which composites the group once, not
     * `fill-opacity`, which each child would apply on its own - so a piece
     * can be outlined in its own colour to close the anti-aliased seam
     * against its neighbour without the overlap printing as a darker line. */
    var fill = svgEl('g', { opacity: 0.85 });
    f.plot.appendChild(fill);
    function fillPiece(piece, colour) {
      if (piece.length < 3) return;
      /* A triangle with an edge lying exactly on a level - which is the
       * ordinary case here, because the outermost levels are the smallest and
       * largest readings themselves - clips to a polygon of no area. Drawing
       * it adds an invisible path per triangle per level and nothing else. */
      var twice = 0, j;
      for (j = 0; j < piece.length; j += 1) {
        var u = piece[j], w = piece[(j + 1) % piece.length];
        twice += u[0] * w[1] - w[0] * u[1];
      }
      if (Math.abs(twice) < 1e-12) return;
      var d = '', i;
      for (i = 0; i < piece.length; i += 1) {
        d += (i ? 'L' : 'M') + f.fx(piece[i][0]).toFixed(2) + ' ' +
          f.fy(piece[i][1]).toFixed(2);
      }
      fill.appendChild(svgEl('path', {
        d: d + 'Z', fill: colour, stroke: colour, 'stroke-width': 0.6,
        'stroke-linejoin': 'round',
      }));
    }
    (geometry.triangles || []).forEach(function (tri) {
      var poly = tri.map(function (idx) { return [xs[idx], logY[idx], rho[idx]]; });
      fillPiece(clipPolygonByValue(poly, false, levels[0]), rampColour('viridis', 0));
      var k;
      for (k = 0; k < levels.length - 1; k += 1) {
        /* A band takes the colour of the value halfway along it *on the
         * scale it is drawn on*, which here is logarithmic: contour.py's
         * _process_levels sets layers to sqrt(l[k]) * sqrt(l[k+1]) when the
         * norm is a LogNorm, not to the arithmetic mean. Taking the
         * arithmetic mean put every band up the ramp from the one matplotlib
         * paints - six parts in 255 on a four-decade section, which is more
         * than the whole error of the ramp table itself - and a pseudo-section
         * is read by matching a colour against the bar beside it. */
        fillPiece(
          clipPolygonByValue(clipPolygonByValue(poly, true, levels[k]),
            false, levels[k + 1]),
          colourFor(Math.sqrt(levels[k]) * Math.sqrt(levels[k + 1])));
      }
      fillPiece(clipPolygonByValue(poly, true, levels[levels.length - 1]),
        rampColour('viridis', 1));
    });

    /* and the readings themselves on top: the colour between two stations is
     * interpolation, the dots are where the instrument actually was */
    xs.forEach(function (x, i) {
      f.plot.appendChild(marker(f.fx(x), f.fy(logY[i]), 'circle',
        colourFor(rho[i]), ON_RAMP_INK, 3.6));
    });

    /* Station names above the shallowest reading, the end ones leaning
     * inwards so they stay on the page. */
    var top = Math.min.apply(null, logY);
    (geometry.stations_m || []).forEach(function (station, k) {
      var anchor = 'middle';
      if (geometry.stations_m.length > 1 && k === 0) anchor = 'start';
      else if (geometry.stations_m.length > 1 &&
        k === geometry.stations_m.length - 1) anchor = 'end';
      f.svg.appendChild(svgEl('text', {
        x: f.fx(station), y: f.fy(top) - 6, 'text-anchor': anchor,
        'font-size': 9, 'font-weight': 700, fill: p.accent,
        stroke: p.surface, 'stroke-width': 3, 'paint-order': 'stroke',
        text: geometry.labels[k],
      }));
    });

    colourBar(f, {
      x: f.margin.left + f.plotW + 14, top: f.margin.top, height: f.plotH,
      range: range, ramp: 'viridis', label: geometry.cbar_label,
    });

    noteBelow(f, noteLines, p.muted, 8.5, 11);
    return f.svg;
  }

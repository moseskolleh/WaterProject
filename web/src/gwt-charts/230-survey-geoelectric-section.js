
  /* ------------------------------------------------- the geoelectric section */

  /* ves/plots.py plot_geoelectric_section: the layer columns at the chainage
   * the soundings were actually surveyed at, boundaries joined only across the
   * gaps the engine says may be correlated, and the note that says which are
   * not. `section` is what C.geoelectricSectionGeometry returned; a section
   * carrying a reason is not drawn at all. */
  function geoelectricSection(section, options) {
    if (!section || section.reason) return null;
    var opts = options || {};
    var models = section.models || [];
    var positions = section.positions_m || [];
    if (!models.length || models.length !== positions.length) return null;

    var depthMax = section.depth_max_m;
    var halfW = section.half_width_m;
    var lo = Math.min.apply(null, positions) - halfW;
    var hi = Math.max.apply(null, positions) + halfW;
    /* matplotlib autoscales a fill_between with a 5% margin either side, so
     * the outermost column does not stand against the frame */
    var airX = (hi - lo) * 0.05 || 1;
    var width = opts.width || 760;
    var noteLines = section.note ? wrapText(section.note, width - 170, 9) : [];
    var base = Math.round(width * 3.6 / FIGURE_WIDTH_IN);
    /* This is the one figure here whose title is built from the survey rather
     * than fixed, and it is the longest: "Interpreted geoelectric section,
     * 20,700 m along bearing 312 degrees (soundings up to 1,240 m off the
     * line)" is half as wide again as the figure. Drawn on one line it was
     * cut off at the viewBox and the reader lost the bracket - the words that
     * say the soundings are not on the line the section is drawn along. The
     * title is wrapped instead, and the top margin grows to hold it. */
    var titleText = opts.title || section.title;
    var titleWidth = width - 74;
    var titleLines = wrapText(titleText, titleWidth,
      TITLE_SIZE * TITLE_BOLD_WIDTH).length;
    var height = (opts.height || base) + noteLines.length * 12 +
      (titleLines - 1) * 16;

    /* The note is printed under the axis label, where the Python puts it, so
     * the axis label is drawn here rather than by frame(), which would put it
     * on the last line of the note at the foot of the figure. */
    var f = frame({
      width: width, height: height,
      margin: {
        top: 30 + (titleLines - 1) * 16, right: 104,
        bottom: 46 + noteLines.length * 12, left: 66,
      },
      title: titleText, titleWidth: titleWidth,
      yLabel: section.y_label, yDown: true, grid: false,
      xDomain: [lo - airX, hi + airX], yDomain: [0, depthMax],
    });
    axisLabelBelow(f, section.x_label);
    var p = f.palette;
    var range = section.rho_range;

    models.forEach(function (model, k) {
      var x = positions[k];
      var xa = f.fx(x - halfW), xb = f.fx(x + halfW);
      var tops = model.depths_top || [];
      (model.resistivities || []).forEach(function (rho, i) {
        var top = Number(tops[i]);
        if (!(top < depthMax)) return;
        var bottom = i + 1 < tops.length ? Number(tops[i + 1]) : depthMax;
        bottom = Math.min(bottom, depthMax);
        var ya = f.fy(top), yb = f.fy(bottom);
        f.plot.appendChild(svgEl('rect', {
          x: xa, y: ya, width: Math.max(xb - xa, 1), height: Math.max(yb - ya, 0),
          fill: rhoRampColour(range, rho),
        }, [svgEl('title', {
          text: section.labels[k] + ': ' + C.fmtNum(rho, 4) + ' ohm-m, ' +
            C.formatG(top) + '-' + C.formatG(bottom) + ' m',
        })]));
      });
      tops.slice(1).forEach(function (z) {
        if (!(z < depthMax)) return;
        f.plot.appendChild(svgEl('line', {
          x1: xa, y1: f.fy(z), x2: xb, y2: f.fy(z),
          stroke: ON_RAMP_INK, 'stroke-width': 1.2,
        }));
      });
    });

    /* A boundary is joined between two neighbouring stations only where the
     * engine's correlation flag allows it. Two soundings too far apart to
     * share a horizon stand as separate columns, because a dashed line drawn
     * between them is a line between two points, not a horizon anybody
     * traced, and it is read as one. */
    var correlate = section.correlate || [];
    var a;
    for (a = 0; a < models.length - 1; a += 1) {
      if (!correlate[a]) continue;
      var m1 = models[a], m2 = models[a + 1];
      var shared = Math.min(m1.n_layers, m2.n_layers) - 1;
      var kk;
      for (kk = 1; kk <= shared; kk += 1) {
        var z1 = m1.depths_top[kk], z2 = m2.depths_top[kk];
        if (z1 === undefined || z2 === undefined) continue;
        if (!(z1 < depthMax) && !(z2 < depthMax)) continue;
        f.plot.appendChild(svgEl('line', {
          x1: f.fx(positions[a] + halfW), y1: f.fy(Math.min(z1, depthMax)),
          x2: f.fx(positions[a + 1] - halfW), y2: f.fy(Math.min(z2, depthMax)),
          stroke: p.muted, 'stroke-width': 1, 'stroke-dasharray': '5 4',
        }));
      }
    }

    (section.labels || []).forEach(function (label, k) {
      f.svg.appendChild(svgEl('text', {
        x: f.fx(positions[k]), y: f.fy(depthMax * 0.035) + 8,
        'text-anchor': 'middle', 'font-size': 10, 'font-weight': 700,
        fill: p.accent, stroke: p.surface, 'stroke-width': 3.2,
        'paint-order': 'stroke', text: label,
      }));
    });

    colourBar(f, {
      x: f.margin.left + f.plotW + 14, top: f.margin.top,
      height: f.plotH, range: range, ramp: 'viridis',
      label: section.cbar_label,
    });

    /* The note says what the figure cannot, so it is on the figure and not in
     * a caption a reader can skip: chiefly that a boundary drawn across a gap
     * much larger than the depth of investigation was not traced. */
    noteBelow(f, noteLines, p.critical, 9, 12);
    return f.svg;
  }

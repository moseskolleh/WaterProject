
  /* ------------------------------------------------- the layer pseudo-section */

  /* ves/plots.py plot_model_pseudosection: one sounding's layer column to
   * scale, coloured on the same logarithmic resistivity bar the section uses.
   * The "pseudo-section showing apparent resistivity and layer thicknesses"
   * figure of the survey reports. */
  function modelPseudosection(model, options) {
    if (!model || !model.resistivities || !model.resistivities.length) return null;
    var opts = options || {};
    var tops = model.depths_top || [];
    /* given the depth of investigation, the column is drawn to the depth the
     * curve's model panel is drawn to, with the depth of investigation
     * dashed where the column runs past it: drawn to the depth of
     * investigation alone, a basement below it was left off the column */
    var depthMax;
    if (opts.depthMax !== undefined && opts.depthMax !== null) {
      depthMax = Number(opts.depthMax);
    } else if (opts.investigationDepth) {
      depthMax = C.modelDepthM(model, opts.investigationDepth);
    } else {
      depthMax = (tops.length > 1 ? Number(tops[tops.length - 1]) : 10) * 1.35 + 3;
    }
    var width = opts.width || 420;
    var height = opts.height || Math.round(width * 3.6 / (FIGURE_WIDTH_IN * 0.72));

    var f = frame({
      width: width, height: height,
      margin: { top: 30, right: 108, bottom: 34, left: 60 },
      title: opts.title || ((model.sounding_id || 'VES') + ' layer section'),
      yLabel: 'Depth (m)', yDown: true, grid: false,
      xDomain: [0, 1], yDomain: [0, depthMax], xTicks: [],
    });
    var range = C.rhoColourRange([model]);

    model.resistivities.forEach(function (rho, i) {
      var top = Number(tops[i]);
      if (!(top < depthMax)) return;
      var bottom = i + 1 < tops.length ? Number(tops[i + 1]) : depthMax;
      bottom = Math.min(bottom, depthMax);
      var ya = f.fy(top), yb = f.fy(bottom);
      f.plot.appendChild(svgEl('rect', {
        x: f.margin.left, y: ya, width: f.plotW, height: Math.max(yb - ya, 0),
        fill: rhoRampColour(range, rho),
      }, [svgEl('title', {
        text: C.fmtNum(rho, 4) + ' ohm-m, ' + C.formatG(top) + '-' +
          C.formatG(bottom) + ' m',
      })]));
      /* the resistivity is written on its own band, on a plate dark enough to
       * read against every colour on the ramp */
      var text = C.fmtNum(rho, 4) + ' ohm-m';
      var cx = f.margin.left + f.plotW / 2, cy = (ya + yb) / 2;
      var tw = textWidth(text, 10);
      f.plot.appendChild(svgEl('rect', {
        x: cx - tw / 2 - 5, y: cy - 9, width: tw + 10, height: 18, rx: 4,
        fill: '#000000', 'fill-opacity': 0.33,
      }));
      f.plot.appendChild(svgEl('text', {
        x: cx, y: cy + 3.6, 'text-anchor': 'middle', 'font-size': 10,
        fill: ON_RAMP_INK, text: text,
      }));
    });
    tops.slice(1).forEach(function (z) {
      if (!(z < depthMax)) return;
      f.plot.appendChild(svgEl('line', {
        x1: f.margin.left, y1: f.fy(z), x2: f.margin.left + f.plotW, y2: f.fy(z),
        stroke: ON_RAMP_INK, 'stroke-width': 1.2,
      }));
    });
    markInvestigationDepth(f, opts.investigationDepth, depthMax);

    colourBar(f, {
      x: f.margin.left + f.plotW + 14, top: f.margin.top, height: f.plotH,
      range: range, ramp: 'viridis', label: 'Resistivity (ohm-m)',
    });
    return f.svg;
  }

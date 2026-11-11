
  /* ============================================================ VES figures */

  /* Sounding curve: measured points, the model response and, on a second
   * axis-free overlay, the layered model as a depth-resistivity staircase. */
  function vesCurve(result, options) {
    var opts = options || {};
    var ab2 = result.ab2, obs = result.rho_obs, calc = result.rho_calc;
    /* the fan: the responses of a thinned set of the models that fit (the
     * range of models, PLAN.md step 3.1), at the same spacings */
    var fan = opts.fan || [];
    var fanValues = [];
    fan.forEach(function (curve) { fanValues = fanValues.concat(curve); });
    var f = frame({
      width: opts.width || 720, height: opts.height || 430,
      title: opts.title || ('Sounding curve - ' + (result.model.sounding_id || 'VES')),
      xLabel: String(result.array_type || '').indexOf('wenner') === 0
        ? 'a (m)' : 'AB/2 (m)',
      yLabel: 'Apparent resistivity (ohm-m)',
      xLog: true, yLog: true,
      xDomain: padDomain(ab2, true),
      yDomain: padDomain(obs.concat(calc, fanValues), true),
    });
    var p = f.palette;

    fan.forEach(function (curve) {
      f.plot.appendChild(polyline(curve.map(function (v, i) {
        return [f.fx(ab2[i]), f.fy(v)];
      }), { stroke: p.muted, 'stroke-width': 1, 'stroke-opacity': 0.35 }));
    });

    if (calc && calc.length) {
      f.plot.appendChild(polyline(calc.map(function (v, i) {
        return [f.fx(ab2[i]), f.fy(v)];
      }), { stroke: p.secondary, 'stroke-width': 2 }));
    }
    var points = [];
    ab2.forEach(function (x, i) {
      var px = f.fx(x), py = f.fy(obs[i]);
      f.plot.appendChild(marker(px, py, 'circle', p.accent, p.surface));
      points.push({ px: px, py: py, x: x, y: obs[i] });
    });

    legend(f, [
      { label: 'Measured', kind: 'circle', colour: p.accent },
      { label: 'Model response', kind: 'line', colour: p.secondary },
    ].concat(fan.length
      ? [{ label: 'Models that fit', kind: 'line', colour: p.muted }] : []), { avoid: points });

    if (opts.hover !== false) {
      addHover(f, [{ label: 'Measured', points: points }], {
        format: function (pt) {
          return 'AB/2 ' + S.sig(pt.x, 3) + ' m · ' + S.sig(pt.y, 4) + ' ohm-m';
        },
      });
    }

    if (result.fit_error_percent !== null && result.fit_error_percent !== undefined) {
      f.svg.appendChild(svgEl('text', {
        x: f.width - f.margin.right, y: 18, 'text-anchor': 'end',
        'font-size': 11.5, fill: p.inkSoft,
        text: 'fit error ' + result.fit_error_percent.toFixed(1) + '%  ·  ' +
          result.model.n_layers + ' layers',
      }));
    }
    return f.svg;
  }

  /* The layered model as a depth staircase, drawn beside the curve. */
  function layeredModel(model, options) {
    var opts = options || {};
    var rho = model.resistivities, h = model.thicknesses;
    var bottom = h.reduce(function (a, v) { return a + v; }, 0);
    var maxDepth = opts.maxDepth || Math.max(bottom * 1.35, bottom + 8, 20);
    /* the fan: a thinned set of the models that fit (the range of models,
     * PLAN.md step 3.1), as [resistivities, thicknesses], drawn grey under
     * the best fit as ves/plots.py draws them on its model panel */
    var fan = opts.fan || [];
    var fanRho = [];
    fan.forEach(function (m) { fanRho = fanRho.concat(m[0]); });
    var f = frame({
      width: opts.width || 340, height: opts.height || 430,
      margin: { top: 30, right: 22, bottom: 56, left: 56 },
      title: opts.title || 'Layered model',
      xLabel: 'Resistivity (\u03A9\u00B7m)', yLabel: 'Depth (m)',
      xLog: true, yDown: true,
      xDomain: padDomain(rho.concat(fanRho), true, 0.12), yDomain: [0, maxDepth],
    });
    var p = f.palette;

    /* the drilling depth's band (PLAN.md step 3.6): the P10 to P90 of the
     * depth each model that fits would be drilled to, shaded across the
     * panel, as ves/plots.py shades it */
    var band = opts.drillBand;
    if (band && band[1] >= band[0]) {
      var top = Math.min(band[0], maxDepth), base = Math.min(band[1], maxDepth);
      f.plot.appendChild(svgEl('rect', {
        x: f.margin.left, y: f.fy(top), width: f.plotW,
        height: Math.max(f.fy(base) - f.fy(top), 1.5),
        fill: p.accent, 'fill-opacity': 0.14,
      }));
      f.plot.appendChild(svgEl('text', {
        x: f.margin.left + 4, y: f.fy(top) - 3, 'font-size': 9, fill: p.inkSoft,
        stroke: p.surface, 'stroke-width': 2.4, 'paint-order': 'stroke',
        text: 'drilling depth, P10 to P90',
      }));
    }
    fan.forEach(function (m) {
      var fanPts = [], z = 0;
      m[0].forEach(function (r, i) {
        var below = i < m[1].length ? z + m[1][i] : maxDepth;
        fanPts.push([f.fx(r), f.fy(Math.min(z, maxDepth))]);
        fanPts.push([f.fx(r), f.fy(Math.min(below, maxDepth))]);
        z = below;
      });
      f.plot.appendChild(polyline(fanPts, { stroke: p.muted, 'stroke-width': 1,
        'stroke-opacity': 0.35 }));
    });

    var pts = [], depth = 0;
    rho.forEach(function (r, i) {
      var top = depth;
      var base = i < h.length ? depth + h[i] : maxDepth;
      pts.push([f.fx(r), f.fy(top)]);
      pts.push([f.fx(r), f.fy(Math.min(base, maxDepth))]);
      depth = base;
    });
    f.plot.appendChild(polyline(pts, { stroke: p.secondary, 'stroke-width': 2.2 }));

    /* The resistivity of a layer is written against that layer. A thin layer
     * at the surface has its midpoint above the top of the plot, and two thin
     * layers together have midpoints a few pixels apart, so the anchors are
     * collected first and then pushed apart inside the frame rather than
     * written where they fall. */
    var marks = [];
    depth = 0;
    rho.forEach(function (r, i) {
      var top = depth;
      var base = i < h.length ? depth + h[i] : maxDepth;
      marks.push({
        anchor: f.fy((top + Math.min(base, maxDepth)) / 2),
        x: f.fx(r), text: C.fmtNum(r, 3) + ' \u03A9\u00B7m',
      });
      if (i < h.length) {
        f.plot.appendChild(svgEl('line', {
          x1: f.margin.left, y1: f.fy(base), x2: f.margin.left + f.plotW, y2: f.fy(base),
          stroke: p.axis, 'stroke-width': 1, 'stroke-dasharray': '4 3',
        }));
      }
      depth = base;
    });
    stackLabels(marks, 15, f.margin.top + 8, f.margin.top + f.plotH - 4)
      .forEach(function (item) {
        var e = item.entry;
        var w = textWidth(e.text, 10.5);
        /* keep the label inside the frame whichever side of the step it is on */
        var flip = e.x + 8 + w > f.margin.left + f.plotW;
        if (flip && e.x - 8 - w < f.margin.left) flip = false;
        f.plot.appendChild(svgEl('text', {
          x: flip ? e.x - 8 : e.x + 8, y: item.y + 4, 'font-size': 10.5,
          'text-anchor': flip ? 'end' : 'start', fill: p.inkSoft, text: e.text,
        }));
      });
    markInvestigationDepth(f, opts.investigationDepth, maxDepth);
    return f.svg;
  }

  /* ves/plots.py _mark_investigation_depth: a dashed line at the depth of
   * investigation, where a figure of one sounding's model runs past it to
   * keep the deepest fitted interface on it. */
  function markInvestigationDepth(f, depth, depthMax) {
    if (depth === null || depth === undefined || !(Number(depth) < depthMax)) return;
    var y = f.fy(Number(depth));
    f.plot.appendChild(svgEl('line', {
      x1: f.margin.left, y1: y, x2: f.margin.left + f.plotW, y2: y,
      stroke: f.palette.critical, 'stroke-width': 1.2, 'stroke-dasharray': '5 3',
    }));
    f.plot.appendChild(svgEl('text', {
      x: f.margin.left + f.plotW - 4, y: y - 3, 'text-anchor': 'end',
      'font-size': 9, fill: f.palette.critical, stroke: f.palette.surface,
      'stroke-width': 2.4, 'paint-order': 'stroke', text: 'depth of investigation',
    }));
  }

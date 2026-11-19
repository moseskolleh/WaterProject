
  /* --- the calibration report's two figures (PLAN.md step 5.2) ------------
   * calibration_plots.py's twins: the depth to basement found against the
   * depth the best fit gave, from C.depthScores, and the reliability
   * diagram, from C.oddsScores. */

  /* a point's place: the depth predicted (the best fit's, else the band's
   * P50, which the figure draws hollow), the depth found or, short of
   * basement, the total depth */
  function calibrationWhere(point) {
    var band = point.band;
    var fallback = point.predicted === null;
    var x = !fallback ? point.predicted : (band ? band[1] : null);
    if (point.found !== null) return { x: x, y: point.found, short: false, fallback: fallback };
    return { x: x, y: point.total_depth_m, short: true, fallback: fallback };
  }

  /* a triangle pointing down: basement lies deeper than the mark */
  function downMark(x, y, colour, ring) {
    var r = 5;
    return svgEl('path', {
      d: 'M' + (x - r * 1.1) + ' ' + (y - r * 0.8) + 'L' + (x + r * 1.1) + ' ' + (y - r * 0.8) +
        'L' + x + ' ' + (y + r * 1.2) + 'Z',
      fill: colour, stroke: ring, 'stroke-width': 1.6, 'stroke-linejoin': 'round',
    });
  }

  function depthCalibration(depth, options) {
    var opts = options || {};
    var drawn = [];
    depth.points.forEach(function (point) {
      var at = calibrationWhere(point);
      if (at.x !== null && at.y !== null) {
        drawn.push({ point: point, x: at.x, y: at.y, short: at.short, fallback: at.fallback });
      }
    });
    var values = [1.0];
    drawn.forEach(function (d) {
      values.push(d.x, d.y);
      if (d.point.band) values.push(d.point.band[0], d.point.band[2]);
    });
    var top = Math.max.apply(null, values) * 1.08;
    var f = frame({
      width: opts.width || 640, height: opts.height || 460,
      margin: { top: 34, right: 26, bottom: 52, left: 66 },
      xDomain: [0, top], yDomain: [0, top], yDown: true,
      title: opts.title === undefined ? 'Depth to basement, predicted and found' : opts.title,
      xLabel: 'Depth to basement predicted by the best fit (m)',
      yLabel: 'Depth to basement found (m)',
    });
    var p = f.palette;
    f.plot.appendChild(svgEl('line', { x1: f.fx(0), y1: f.fy(0), x2: f.fx(top), y2: f.fy(top),
      stroke: p.neutral, 'stroke-width': 1, 'stroke-dasharray': '5 4' }));
    var kinds = { inside: [p.accent, 'Inside the band'], outside: [p.secondary, 'Outside the band'],
      unjudged: [p.neutral, 'Not judged'] };
    var present = {}, anyShort = false, anyFallback = false, marks = [];
    drawn.forEach(function (d) {
      var check = d.point.check;
      var kind = check === 'inside' ? 'inside'
        : (check === 'shallower' || check === 'deeper' ? 'outside' : 'unjudged');
      present[kind] = true;
      var colour = kinds[kind][0];
      var px = f.fx(d.x), py = f.fy(d.y);
      if (d.point.band) {
        f.plot.appendChild(svgEl('line', { x1: f.fx(d.point.band[0]), y1: py, x2: f.fx(d.point.band[2]),
          y2: py, stroke: colour, 'stroke-width': 1.4, 'stroke-opacity': 0.7 }));
      }
      /* hollow where the depth predicted is the band's P50, not a best fit's */
      var fill = d.fallback ? p.surface : colour, ring = d.fallback ? colour : p.surface;
      f.plot.appendChild(d.short ? downMark(px, py, fill, ring) : marker(px, py, 'circle', fill, ring, 4.5));
      if (d.short) anyShort = true;
      if (d.fallback) anyFallback = true;
      marks.push({ px: px, py: py });
    });
    /** @type {Array<{kind: string, colour: string, label: string, dash?: string}>} */
    var entries = [{ kind: 'line', colour: p.neutral, dash: '5 4', label: 'Found where predicted' }];
    ['inside', 'outside', 'unjudged'].forEach(function (kind) {
      if (present[kind]) entries.push({ kind: 'circle', colour: kinds[kind][0], label: kinds[kind][1] });
    });
    if (anyShort) {
      entries.push({ kind: 'down', colour: p.neutral, label: 'Stopped short of basement, at its total depth' });
    }
    if (anyFallback) entries.push({ kind: 'hollow', colour: p.neutral, label: 'No best fit: at the band\'s P50' });
    legend(f, entries, { avoid: marks });
    return f.svg;
  }

  function reliabilityDiagram(odds, options) {
    var opts = options || {};
    var f = frame({
      width: opts.width || 640, height: opts.height || 460,
      margin: { top: 34, right: 26, bottom: 52, left: 66 },
      xDomain: [0, 100], yDomain: [0, 100],
      xTicks: [0, 20, 40, 60, 80, 100], yTicks: [0, 20, 40, 60, 80, 100],
      title: opts.title === undefined ? 'Reliability of the chance of success' : opts.title,
      xLabel: 'Mean chance forecast (%)', yLabel: 'Boreholes that succeeded (%)',
    });
    var p = f.palette;
    odds.bins.slice(1).forEach(function (b) {
      var x = f.fx(100 * b.low);
      f.plot.appendChild(svgEl('line', { x1: x, y1: f.fy(0), x2: x, y2: f.fy(100), stroke: p.grid,
        'stroke-width': 1 }));
    });
    f.plot.appendChild(svgEl('line', { x1: f.fx(0), y1: f.fy(0), x2: f.fx(100), y2: f.fy(100),
      stroke: p.neutral, 'stroke-width': 1, 'stroke-dasharray': '5 4' }));
    var shown = odds.bins.filter(function (b) { return b.n; });
    var pts = shown.map(function (b) { return [f.fx(100 * b.mean_p), f.fy(100 * b.observed)]; });
    if (pts.length > 1) f.plot.appendChild(polyline(pts, { stroke: p.accent, 'stroke-width': 2 }));
    var marks = [];
    shown.forEach(function (b, i) {
      f.plot.appendChild(marker(pts[i][0], pts[i][1], 'circle', p.accent, p.surface, 4.5));
      f.plot.appendChild(svgEl('text', { x: pts[i][0] + 7, y: pts[i][1] + (b.observed > 0.88 ? 14 : -7),
        'font-size': 10.5, fill: p.neutral, text: String(b.n) }));
      marks.push({ px: pts[i][0], py: pts[i][1] });
    });
    legend(f, [{ kind: 'line', colour: p.neutral, dash: '5 4', label: 'Calibrated' },
      { kind: 'circle', colour: p.accent, label: 'Forecasts, by band of chance' }], { avoid: marks });
    return f.svg;
  }

  /* How long boreholes keep working (PLAN.md step 7.4): for each group
   * judged, the share still working as a step from 100 percent at
   * commissioning, its 95 percent band shaded behind it from the first
   * failure on, and a tick where a borehole was censored at the last report
   * of it working. survival_plots.py plot_survival's twin; groups too few
   * to judge are not drawn. */
  function survivalCurves(groups, options) {
    var opts = options || {};
    var perYear = C.DAYS_PER_YEAR;
    var shown = groups.filter(function (g) { return g.judged; });
    var right = 1.0;
    shown.forEach(function (g) { right = Math.max(right, g.last_days / perYear); });
    var f = frame({
      width: opts.width || 720, height: opts.height || 420,
      margin: { top: 34, right: 26, bottom: 52, left: 66 },
      xDomain: [0, right * 1.04], yDomain: [0, 102], yTicks: [0, 20, 40, 60, 80, 100],
      title: opts.title || C.phrase('survival.figure_all'),
      xLabel: C.phrase('survival.axis_x'), yLabel: C.phrase('survival.axis_y'),
    });
    var p = f.palette;
    var colours = [p.accent, p.secondary].concat(p.cat.slice(2));
    /** @type {Array<{kind: string, colour: string, label: string}>} */
    var entries = [];
    /** @type {Array<{px: number, py: number}>} */
    var marks = [];
    shown.forEach(function (g, i) {
      var colour = colours[i % colours.length];
      var steps = g.steps;
      steps.forEach(function (s, k) {
        if (s.lower === null) return;
        var x0 = f.fx(s.days / perYear);
        var x1 = k + 1 < steps.length ? f.fx(steps[k + 1].days / perYear) : x0;
        if (!(x1 > x0)) return;
        f.plot.appendChild(svgEl('rect', {
          x: x0, y: f.fy(100 * s.upper), width: x1 - x0,
          height: Math.max(f.fy(100 * s.lower) - f.fy(100 * s.upper), 0.5),
          fill: colour, 'fill-opacity': 0.15,
        }));
      });
      var d = 'M' + f.fx(0).toFixed(2) + ' ' + f.fy(100).toFixed(2);
      steps.forEach(function (s) {
        d += 'H' + f.fx(s.days / perYear).toFixed(2) + 'V' + f.fy(100 * s.survival).toFixed(2);
      });
      f.plot.appendChild(svgEl('path', { d: d, fill: 'none', stroke: colour, 'stroke-width': 2,
        'stroke-linejoin': 'round' }));
      steps.forEach(function (s) {
        var px = f.fx(s.days / perYear), py = f.fy(100 * s.survival);
        marks.push({ px: px, py: py });
        if (!s.censored) return;
        f.plot.appendChild(svgEl('line', { x1: px, y1: py - 5, x2: px, y2: py + 5,
          stroke: colour, 'stroke-width': 1.6 }));
      });
      entries.push({ kind: 'line', colour: colour,
        label: C.phrase('survival.legend', { label: g.label, n: g.n }) });
    });
    if (shown.length) {
      entries.push({ kind: 'tick', colour: p.neutral, label: C.phrase('survival.legend_censored') });
      legend(f, entries, { avoid: marks });
    }
    return f.svg;
  }

  /* A 2px surface gap between adjacent fills keeps segments countable. */
  function roundedBar(x, y, w, h, r) {
    var rad = Math.min(r, w, h / 2);
    return 'M' + x + ' ' + y +
      'H' + (x + w - rad) + 'a' + rad + ' ' + rad + ' 0 0 1 ' + rad + ' ' + rad +
      'V' + (y + h - rad) + 'a' + rad + ' ' + rad + ' 0 0 1 ' + (-rad) + ' ' + rad +
      'H' + x + 'Z';
  }

  /* An indicative programme of works: one bar per borehole across the weeks. */
  function programmeGantt(programme, options) {
    var opts = options || {};
    var p = palette();
    var perWell = opts.daysPerWell ||
      Math.max(3, Math.ceil((programme.well_estimate.inputs.crew_days || 8)));
    var n = programme.n_attempted;
    var totalDays = perWell * n;
    var width = opts.width || 760;
    var rowH = 20, gap = 4;
    var height = 74 + n * (rowH + gap);
    var labelW = 118;
    var plotW = width - labelW - 26;

    var svg = svgEl('svg', {
      viewBox: '0 0 ' + width + ' ' + height, width: '100%', xmlns: NS,
      'font-family': FONT, role: 'img', 'aria-label': 'Indicative programme of works',
    });
    svg.appendChild(svgEl('rect', { width: width, height: height, fill: p.surface }));
    svg.appendChild(svgEl('text', {
      x: 14, y: 22, 'font-size': 13, 'font-weight': 600, fill: p.ink,
      text: opts.title || 'Indicative programme of works',
    }));
    svg.appendChild(svgEl('text', {
      x: 14, y: 38, 'font-size': 10.5, fill: p.muted,
      text: n + ' attempts for ' + programme.n_successful + ' successful boreholes, ' +
        perWell + ' crew days each, one rig',
    }));

    function fx(day) { return labelW + (day / totalDays) * plotW; }
    var weekStep = Math.max(7, Math.ceil(totalDays / 12 / 7) * 7);
    for (var day = 0; day <= totalDays; day += weekStep) {
      svg.appendChild(svgEl('line', {
        x1: fx(day), y1: 50, x2: fx(day), y2: height - 20,
        stroke: p.grid, 'stroke-width': 1,
      }));
      svg.appendChild(svgEl('text', {
        x: fx(day), y: height - 6, 'text-anchor': 'middle', 'font-size': 10,
        fill: p.muted, text: 'wk ' + Math.round(day / 7),
      }));
    }

    for (var i = 0; i < n; i++) {
      var y = 56 + i * (rowH + gap);
      var dry = i >= programme.n_successful;
      svg.appendChild(svgEl('text', {
        x: labelW - 10, y: y + rowH / 2 + 4, 'text-anchor': 'end',
        'font-size': 10.5, fill: p.inkSoft,
        text: dry ? 'attempt ' + (i + 1) + ' (dry)' : 'borehole ' + (i + 1),
      }));
      svg.appendChild(svgEl('path', {
        /* 2px gap between consecutive bars so the sequence reads as separate */
        d: roundedBar(fx(i * perWell) + 1, y, Math.max(3, fx(perWell) - fx(0) - 2),
          rowH, 3),
        fill: dry ? p.cat[3] : p.cat[0],
      }));
    }
    var lg = [
      { label: 'Successful borehole', colour: p.cat[0] },
      { label: 'Expected dry attempt', colour: p.cat[3] },
    ];
    lg.forEach(function (item, i) {
      svg.appendChild(svgEl('rect', {
        x: labelW + i * 170, y: 40, width: 11, height: 11, rx: 2, fill: item.colour,
      }));
      svg.appendChild(svgEl('text', {
        x: labelW + i * 170 + 16, y: 49, 'font-size': 10.5, fill: p.inkSoft,
        text: item.label,
      }));
    });
    return svg;
  }

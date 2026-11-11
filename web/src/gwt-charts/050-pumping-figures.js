
  /* ====================================================== pumping test figures */

  function testOverview(test, analysis, options) {
    var opts = options || {};
    var swl = test.static_water_level_m;
    /* each step on the test's clock, so steps timed from their own start
     * are drawn one after another rather than stacked on the same hour */
    var offsets = C.stepOffsetsMin(test.steps || []);
    var allT = [], allWl = [];
    (test.steps || []).forEach(function (s, i) {
      allT = allT.concat(s.time_min.map(function (t) { return t + offsets[i]; }));
      allWl = allWl.concat(s.water_level_m);
    });
    var recT = test.recovery_time_min || [];
    var duration = test.pumping_duration_min || (allT.length ? Math.max.apply(null, allT) : 0);
    var recShift = recT.map(function (t) { return duration + t; });
    var recWl = test.recovery_level_m || [];
    /* the intake and the hole bottom, so a level past either is seen to be:
     * the pump setting is named as the test's, not a recommendation */
    var refs = [];
    if (test.pump_setting_m) {
      refs.push({ y: test.pump_setting_m, dash: '2 3', colour: null,
        text: 'test pump intake ' + C.pyFixed(test.pump_setting_m, 0) + ' m' });
    }
    if (test.borehole_depth_m) {
      refs.push({ y: test.borehole_depth_m, dash: '6 3 2 3', colour: '#7A5C3A',
        text: 'borehole bottom ' + C.pyFixed(test.borehole_depth_m, 0) + ' m' });
    }
    var refLevels = refs.map(function (r) { return r.y; });

    var f = frame({
      width: opts.width || 760, height: opts.height || 420,
      title: opts.title || 'Pumping test overview',
      xLabel: 'Time since start (min)', yLabel: 'Water level below datum (m)',
      yDown: true,
      xDomain: [0, Math.max.apply(null, [1].concat(allT, recShift)) * 1.02],
      yDomain: padDomain((swl !== null ? [swl] : []).concat(allWl, recWl, refLevels),
        false, 0.08),
    });
    var p = f.palette;

    if (swl !== null && swl !== undefined) {
      f.plot.appendChild(svgEl('line', {
        x1: f.margin.left, y1: f.fy(swl), x2: f.margin.left + f.plotW, y2: f.fy(swl),
        stroke: p.neutral, 'stroke-width': 1.5, 'stroke-dasharray': '6 4',
      }));
      f.plot.appendChild(svgEl('text', {
        x: f.margin.left + 6, y: f.fy(swl) - 5, 'font-size': 10.5, fill: p.inkSoft,
        text: 'static water level ' + swl.toFixed(2) + ' m',
      }));
    }
    refs.forEach(function (ref) {
      f.plot.appendChild(svgEl('line', {
        x1: f.margin.left, y1: f.fy(ref.y), x2: f.margin.left + f.plotW, y2: f.fy(ref.y),
        stroke: ref.colour || p.neutral, 'stroke-width': 1.2, 'stroke-dasharray': ref.dash,
      }));
      f.plot.appendChild(svgEl('text', {
        x: f.margin.left + f.plotW - 6, y: f.fy(ref.y) - 5, 'font-size': 10.5,
        'text-anchor': 'end', fill: p.inkSoft, text: ref.text,
      }));
    });

    var series = [], entries = [];
    (test.steps || []).forEach(function (step, i) {
      var pts = step.time_min.map(function (t, k) {
        var x = t + offsets[i];
        return { px: f.fx(x), py: f.fy(step.water_level_m[k]), x: x, y: step.water_level_m[k] };
      });
      var colour = (test.steps.length > 1) ? p.cat[i % p.cat.length] : p.accent;
      f.plot.appendChild(polyline(pts.map(function (pt) { return [pt.px, pt.py]; }),
        { stroke: colour, 'stroke-width': 2 }));
      pts.forEach(function (pt) {
        f.plot.appendChild(marker(pt.px, pt.py, 'circle', colour, p.surface, 3.4));
      });
      series.push({ label: step.label, points: pts });
      entries.push({
        label: step.label + (step.discharge_m3_per_h
          ? ' (' + S.sig(step.discharge_m3_per_h, 3) + ' m3/h)' : ' (Q pending)'),
        kind: 'circle', colour: colour,
      });
    });

    if (recShift.length) {
      var recPts = recShift.map(function (t, k) {
        return { px: f.fx(t), py: f.fy(recWl[k]), x: t, y: recWl[k] };
      });
      f.plot.appendChild(polyline(recPts.map(function (pt) { return [pt.px, pt.py]; }),
        { stroke: p.secondary, 'stroke-width': 2, 'stroke-dasharray': '5 3' }));
      recPts.forEach(function (pt) {
        f.plot.appendChild(marker(pt.px, pt.py, 'triangle', p.secondary, p.surface, 3.6));
      });
      series.push({ label: 'Recovery', points: recPts });
      entries.push({ label: 'Recovery', kind: 'triangle', colour: p.secondary });
    }

    var allPoints = series.reduce(function (a, s) { return a.concat(s.points); }, []);
    if (entries.length > 1) legend(f, entries, { avoid: allPoints });
    if (opts.hover !== false) {
      addHover(f, series, {
        format: function (pt) {
          return 't = ' + S.sig(pt.x, 4) + ' min · level ' + pt.y.toFixed(2) + ' m';
        },
      });
    }
    return f.svg;
  }

  function cooperJacob(analysis, options) {
    var opts = options || {};
    var cj = analysis.cooper_jacob;
    if (!cj) return null;
    var test = analysis.test, swl = test.static_water_level_m;
    var step = test.steps[0];
    var t = [], s = [];
    step.time_min.forEach(function (v, i) {
      if (v > 0) { t.push(v); s.push(step.water_level_m[i] - swl); }
    });

    var f = frame({
      width: opts.width || 720, height: opts.height || 420,
      title: opts.title || 'Cooper-Jacob straight line fit',
      xLabel: 'Time since pumping started (min, log scale)', yLabel: 'Drawdown (m)',
      xLog: true, yDown: true,
      xDomain: padDomain(t.concat([cj.intercept_t0_min]), true),
      yDomain: padDomain([0].concat(s), false, 0.1),
    });
    var p = f.palette;

    /* the fitted line, drawn across the whole plot so its slope is readable */
    var dom = padDomain(t.concat([cj.intercept_t0_min]), true);
    var lineX = [dom[0], dom[1]];
    f.plot.appendChild(polyline(lineX.map(function (x) {
      return [f.fx(x), f.fy(cj.slope_m_per_log_cycle *
        (Math.log(x) / Math.LN10 - Math.log(cj.intercept_t0_min) / Math.LN10))];
    }), { stroke: p.secondary, 'stroke-width': 2 }));

    /* the fitted window, shaded, so the reader sees which points drove it */
    f.plot.insertBefore(svgEl('rect', {
      x: f.fx(cj.fit_window_min[0]), y: f.margin.top,
      width: Math.max(0, f.fx(cj.fit_window_min[1]) - f.fx(cj.fit_window_min[0])),
      height: f.plotH, fill: p.accent, 'fill-opacity': 0.07,
    }), f.plot.firstChild);

    var pts = [];
    t.forEach(function (x, i) {
      var inWindow = x >= cj.fit_window_min[0] && x <= cj.fit_window_min[1];
      var px = f.fx(x), py = f.fy(s[i]);
      f.plot.appendChild(marker(px, py, 'circle', inWindow ? p.accent : p.accentSoft,
        p.surface, inWindow ? 4.5 : 3.4));
      pts.push({ px: px, py: py, x: x, y: s[i] });
    });

    legend(f, [
      { label: 'Drawdown', kind: 'circle', colour: p.accent },
      { label: 'Fitted straight line', kind: 'line', colour: p.secondary },
    ], { avoid: pts });

    f.svg.appendChild(svgEl('text', {
      x: f.width - f.margin.right, y: 18, 'text-anchor': 'end',
      'font-size': 11.5, fill: p.inkSoft,
      text: 'T = ' + S.sig(cj.transmissivity_m2_per_day, 3) + ' m²/day · Δs = ' +
        cj.slope_m_per_log_cycle.toFixed(2) + ' m/cycle · r² = ' +
        cj.r_squared.toFixed(3),
    }));
    if (opts.hover !== false) {
      addHover(f, [{ label: 'Drawdown', points: pts }], {
        format: function (pt) {
          return 't = ' + S.sig(pt.x, 4) + ' min · s = ' + pt.y.toFixed(2) + ' m';
        },
      });
    }
    return f.svg;
  }

  /* The diagnostic plot (hydraulics/plots.py plot_diagnostic): drawdown and
   * its Bourdet derivative on log-log axes, the regimes the derivative's
   * slope names shaded and labelled, and guides of slope 1 and 1/2 from the
   * first derivative point. Null when the analysis drew no derivative. */
  var REGIME_LABELS = {
    wellbore_storage: 'casing storage', storage_ending: 'end of storage',
    radial_flow: 'radial flow', linear_flow: 'linear flow',
    recharge_boundary: 'recharge boundary', no_flow_boundary: 'no-flow boundary',
    closed_boundary: 'closed boundary',
  };

  function diagnosticPlot(analysis, options) {
    var opts = options || {};
    var d = analysis.diagnostic;
    if (!d) return null;
    var t = d.time_min, s = d.drawdown_m;
    var dt = [], dd = [];
    d.derivative_time_min.forEach(function (x, i) {
      if (d.derivative_m[i] > 0) { dt.push(x); dd.push(d.derivative_m[i]); }
    });
    var f = frame({
      width: opts.width || 720, height: opts.height || 420,
      title: opts.title || 'Diagnostic plot (Bourdet derivative)',
      xLabel: 'Time since pumping started (min, log scale)',
      yLabel: 'Drawdown and derivative (m)',
      xLog: true, yLog: true,
      xDomain: padDomain(t, true), yDomain: padDomain(s.concat(dd), true),
    });
    var p = f.palette;

    d.regimes.forEach(function (r, k) {
      var x0 = f.fx(r.start_min), x1 = f.fx(r.end_min);
      f.plot.insertBefore(svgEl('rect', {
        x: x0, y: f.margin.top, width: Math.max(0, x1 - x0), height: f.plotH,
        fill: p.accent, 'fill-opacity': k % 2 ? 0.11 : 0.06,
      }), f.plot.firstChild);
      f.plot.appendChild(svgEl('text', {
        x: (x0 + x1) / 2, y: f.margin.top + 14, 'text-anchor': 'middle',
        'font-size': 10.5, fill: p.inkSoft, text: REGIME_LABELS[r.key] || r.key,
      }));
    });

    if (dt.length) {
      /* slope guides through the first derivative point */
      var x0g = dt[0], y0g = dd[0];
      var x1g = Math.max(Math.min(x0g * 10, t[t.length - 1]), x0g * 1.5);
      [1, 0.5].forEach(function (slope) {
        f.plot.appendChild(polyline([[f.fx(x0g), f.fy(y0g)],
          [f.fx(x1g), f.fy(y0g * Math.pow(x1g / x0g, slope))]],
        { stroke: p.neutral, 'stroke-width': 1, 'stroke-dasharray': '2 3' }));
      });
    }

    var pts = [], dpts = [];
    t.forEach(function (x, i) {
      var px = f.fx(x), py = f.fy(s[i]);
      f.plot.appendChild(marker(px, py, 'circle', p.accent, p.surface));
      pts.push({ px: px, py: py, x: x, y: s[i] });
    });
    dt.forEach(function (x, i) {
      var px = f.fx(x), py = f.fy(dd[i]);
      f.plot.appendChild(marker(px, py, 'triangle', p.secondary, p.surface));
      dpts.push({ px: px, py: py, x: x, y: dd[i] });
    });

    legend(f, [
      { label: 'Drawdown s', kind: 'circle', colour: p.accent },
      { label: 'Derivative ds/d ln t (L = ' + C.formatG(d.l_log10) + ' log cycle)',
        kind: 'triangle', colour: p.secondary },
      { label: 'Slopes 1 and 1/2', kind: 'line', colour: p.neutral },
    ], { avoid: pts.concat(dpts) });

    if (opts.hover !== false) {
      addHover(f, [{ label: 'Drawdown', points: pts }, { label: 'Derivative', points: dpts }], {
        format: function (pt) {
          return 't = ' + S.sig(pt.x, 4) + ' min · ' + S.sig(pt.y, 3) + ' m';
        },
      });
    }
    return f.svg;
  }

  function recoveryPlot(analysis, options) {
    var opts = options || {};
    var rec = analysis.recovery;
    if (!rec) return null;
    var test = analysis.test, swl = test.static_water_level_m;
    var tp = test.recovery_time_min || [], levels = test.recovery_level_m || [];
    /* t/t' is formed with the pumping time the fit used: the pumped duration
     * of a constant test, or the equivalent time after a step test */
    var pumpingTime = rec.pumping_time_min || test.pumping_duration_min;
    var ratio = [], residual = [];
    tp.forEach(function (v, i) {
      if (v > 0) {
        ratio.push((pumpingTime + v) / v);
        residual.push(levels[i] - swl);
      }
    });

    var f = frame({
      width: opts.width || 720, height: opts.height || 400,
      title: opts.title || 'Theis recovery',
      xLabel: "t / t' (log scale)", yLabel: "Residual drawdown s' (m)",
      xLog: true, yDown: true,
      xDomain: padDomain(ratio.concat([1]), true),
      yDomain: padDomain([0, rec.intercept_m].concat(residual), false, 0.1),
    });
    var p = f.palette;
    var dom = padDomain(ratio.concat([1]), true);
    f.plot.appendChild(polyline([dom[0], dom[1]].map(function (x) {
      return [f.fx(x), f.fy(rec.slope_m_per_log_cycle * Math.log(x) / Math.LN10 +
        rec.intercept_m)];
    }), { stroke: p.secondary, 'stroke-width': 2 }));

    var pts = [];
    ratio.forEach(function (x, i) {
      var px = f.fx(x), py = f.fy(residual[i]);
      f.plot.appendChild(marker(px, py, 'circle', p.accent, p.surface));
      pts.push({ px: px, py: py, x: x, y: residual[i] });
    });
    /* where theory says the line meets t/t' = 1, and where this one does */
    f.plot.appendChild(svgEl('line', {
      x1: f.fx(1), y1: f.margin.top, x2: f.fx(1), y2: f.margin.top + f.plotH,
      stroke: p.neutral, 'stroke-width': 1, 'stroke-dasharray': '2 3',
    }));
    f.plot.appendChild(marker(f.fx(1), f.fy(rec.intercept_m), 'diamond',
      p.secondary, p.surface, 5));
    pts.push({ px: f.fx(1), py: f.fy(rec.intercept_m), x: 1, y: rec.intercept_m });
    legend(f, [
      { label: 'Residual drawdown', kind: 'circle', colour: p.accent },
      { label: 'Fitted line', kind: 'line', colour: p.secondary },
      { label: 'intercept ' + rec.intercept_m.toFixed(1) + ' m (theory: 0)',
        kind: 'diamond', colour: p.secondary },
    ], { avoid: pts });
    f.svg.appendChild(svgEl('text', {
      x: f.width - f.margin.right, y: 18, 'text-anchor': 'end',
      'font-size': 11.5, fill: p.inkSoft,
      text: 'T = ' + S.sig(rec.transmissivity_m2_per_day, 3) + ' m²/day · r² = ' +
        rec.r_squared.toFixed(3),
    }));
    if (rec.equivalent_time) {
      f.plot.appendChild(svgEl('text', {
        x: f.margin.left + 8, y: f.margin.top + f.plotH - 8, 'font-size': 10.5,
        fill: p.inkSoft,
        text: 't = equivalent pumping time ' + C.pyFixed(pumpingTime, 0) + ' min',
      }));
    }
    if (opts.hover !== false) {
      addHover(f, [{ label: 'Recovery', points: pts }], {
        format: function (pt) {
          return "t/t' = " + S.sig(pt.x, 4) + " · s' = " + pt.y.toFixed(2) + ' m';
        },
      });
    }
    return f.svg;
  }

  /* Hantush-Bierschenk: s/Q against Q, whose slope is the well loss and whose
   * intercept is the aquifer loss. */
  function stepTestPlot(analysis, options) {
    var opts = options || {};
    var st = analysis.step_test;
    if (!st) return null;
    var q = st.steps.map(function (s) { return s.discharge_m3_per_h * 24.0; });
    var sq = st.steps.map(function (s) { return s.sw_over_q_day_per_m2; });

    /* a line through two points is exact by construction, and the title
     * says so rather than letting an r² of 1.000 stand as a result */
    var f = frame({
      width: opts.width || 620, height: opts.height || 400,
      title: opts.title || ('Step drawdown analysis (Hantush-Bierschenk' +
        (st.two_point ? ', two points' : '') + ')'),
      xLabel: 'Discharge Q (m³/day)', yLabel: 'Specific drawdown s/Q (day/m²)',
      xDomain: [0, Math.max.apply(null, q) * 1.12],
      yDomain: padDomain([0].concat(sq), false, 0.15),
    });
    var p = f.palette;

    f.plot.appendChild(polyline([0, Math.max.apply(null, q) * 1.12].map(function (x) {
      return [f.fx(x), f.fy(st.aquifer_loss_B + st.well_loss_C * x)];
    }), { stroke: p.secondary, 'stroke-width': 2 }));

    var pts = [];
    q.forEach(function (x, i) {
      var px = f.fx(x), py = f.fy(sq[i]);
      f.plot.appendChild(marker(px, py, 'circle', p.accent, p.surface, 5.5));
      f.plot.appendChild(svgEl('text', {
        x: px, y: py - 12, 'text-anchor': 'middle', 'font-size': 10.5,
        fill: p.inkSoft,
        text: 'step ' + st.steps[i].step + ' · ' +
          st.steps[i].efficiency_percent.toFixed(0) + '% eff',
      }));
      pts.push({ px: px, py: py, x: x, y: sq[i] });
    });

    legend(f, [
      { label: 'Measured steps', kind: 'circle', colour: p.accent },
      { label: 's/Q = B + C·Q', kind: 'line', colour: p.secondary },
    ], { avoid: pts });

    f.svg.appendChild(svgEl('text', {
      x: f.width - f.margin.right, y: 18, 'text-anchor': 'end',
      'font-size': 11.5, fill: p.inkSoft,
      text: 'B = ' + S.sig(st.aquifer_loss_B, 3) + ' · C = ' +
        S.sig(st.well_loss_C, 3) +
        (st.two_point ? ' · two points, exact by construction'
          : ' · r² = ' + st.r_squared.toFixed(3)),
    }));
    return f.svg;
  }

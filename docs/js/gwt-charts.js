/* gwt-charts.js - every figure the toolkit draws, as inline SVG.
 *
 * No plotting library: the figures are small, specific and need to match the
 * matplotlib originals that go into the .docx reports, so they are drawn
 * directly. Each function returns an <svg> element that can be shown on the
 * page and rasterised to PNG for a report by toPng().
 *
 * Colour is taken from the stylesheet's tokens at draw time and written into
 * the SVG as literal values, so a figure exports correctly and a theme change
 * simply redraws. Field data is always the blue and a fitted model always the
 * orange, and the two are additionally separated by mark type, so the pair
 * never depends on hue alone.
 */
(function (global) {
  'use strict';

  var GWT = global.GWT || (global.GWT = {});
  var S = GWT.support;
  var C = GWT.core;
  var svgEl = S.svgEl, el = S.el;

  var NS = 'http://www.w3.org/2000/svg';

  /* ------------------------------------------------------------ palette */

  function token(name, fallback) {
    if (typeof getComputedStyle === 'undefined') return fallback;
    var value = getComputedStyle(document.documentElement)
      .getPropertyValue('--' + name);
    return (value || '').trim() || fallback;
  }

  function palette() {
    return {
      surface: token('viz-surface', '#FFFFFF'),
      grid: token('viz-grid', '#e1e0d9'),
      axis: token('viz-axis', '#c3c2b7'),
      muted: token('viz-muted', '#898781'),
      ink: token('ink', '#152220'),
      inkSoft: token('ink-soft', '#4A5B56'),
      accent: token('accent', '#155D92'),
      accentSoft: token('accent-soft', '#86b6ef'),
      secondary: token('secondary', '#C15A2A'),
      neutral: token('neutral', '#4D4D4D'),
      cat: [1, 2, 3, 4, 5, 6, 7, 8].map(function (i) {
        return token('cat-' + i, '#2a78d6');
      }),
      seq: [1, 2, 3, 4, 5, 6, 7].map(function (i) {
        return token('seq-' + i, '#3987e5');
      }),
      good: token('status-good', '#0ca30c'),
      warning: token('status-warning', '#fab219'),
      serious: token('status-serious', '#ec835a'),
      critical: token('status-critical', '#d03b3b'),
    };
  }

  /* --------------------------------------------------------------- frame */

  var FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif';

  /* A plot frame with linear or logarithmic scales. Returns the <svg>, the
   * plotting group and the x/y mapping functions the callers draw into. */
  function frame(spec) {
    var p = palette();
    var width = spec.width || 720;
    var height = spec.height || 420;
    var margin = Object.assign({ top: 30, right: 22, bottom: 52, left: 66 },
      spec.margin || {});
    var plotW = width - margin.left - margin.right;
    var plotH = height - margin.top - margin.bottom;

    var svg = svgEl('svg', {
      viewBox: '0 0 ' + width + ' ' + height,
      width: '100%', xmlns: NS, 'font-family': FONT,
      role: 'img', 'aria-label': spec.title || 'figure',
    });
    svg.appendChild(svgEl('rect', {
      x: 0, y: 0, width: width, height: height, fill: p.surface,
    }));

    var xLog = spec.xLog, yLog = spec.yLog;
    var xd = spec.xDomain, yd = spec.yDomain;
    function fx(v) {
      var a = xLog ? Math.log(v) : v;
      var lo = xLog ? Math.log(xd[0]) : xd[0], hi = xLog ? Math.log(xd[1]) : xd[1];
      return margin.left + (hi === lo ? 0 : (a - lo) / (hi - lo)) * plotW;
    }
    function fy(v) {
      var a = yLog ? Math.log(v) : v;
      var lo = yLog ? Math.log(yd[0]) : yd[0], hi = yLog ? Math.log(yd[1]) : yd[1];
      var t = hi === lo ? 0 : (a - lo) / (hi - lo);
      return spec.yDown ? margin.top + t * plotH : margin.top + (1 - t) * plotH;
    }

    var grid = svgEl('g', { 'aria-hidden': 'true' });
    svg.appendChild(grid);

    var xTicks = spec.xTicks || (xLog ? logTicks(xd) : linTicks(xd, 6));
    var yTicks = spec.yTicks || (yLog ? logTicks(yd) : linTicks(yd, 6));

    xTicks.forEach(function (t) {
      var x = fx(t.value === undefined ? t : t.value);
      if (!isFinite(x)) return;
      grid.appendChild(svgEl('line', {
        x1: x, y1: margin.top, x2: x, y2: margin.top + plotH,
        stroke: p.grid, 'stroke-width': 1,
      }));
      grid.appendChild(svgEl('text', {
        x: x, y: margin.top + plotH + 17, 'text-anchor': 'middle',
        'font-size': 11, fill: p.muted,
        text: t.label === undefined ? tickLabel(t) : t.label,
      }));
    });
    yTicks.forEach(function (t) {
      var y = fy(t.value === undefined ? t : t.value);
      if (!isFinite(y)) return;
      grid.appendChild(svgEl('line', {
        x1: margin.left, y1: y, x2: margin.left + plotW, y2: y,
        stroke: p.grid, 'stroke-width': 1,
      }));
      grid.appendChild(svgEl('text', {
        x: margin.left - 8, y: y + 4, 'text-anchor': 'end',
        'font-size': 11, fill: p.muted,
        text: t.label === undefined ? tickLabel(t) : t.label,
      }));
    });

    /* baseline and left axis only - a full box adds ink without meaning */
    svg.appendChild(svgEl('line', {
      x1: margin.left, y1: margin.top + plotH, x2: margin.left + plotW,
      y2: margin.top + plotH, stroke: p.axis, 'stroke-width': 1,
    }));
    svg.appendChild(svgEl('line', {
      x1: margin.left, y1: margin.top, x2: margin.left, y2: margin.top + plotH,
      stroke: p.axis, 'stroke-width': 1,
    }));

    if (spec.title) {
      svg.appendChild(svgEl('text', {
        x: margin.left, y: 18, 'font-size': 13, 'font-weight': 600,
        fill: p.ink, text: spec.title,
      }));
    }
    if (spec.xLabel) {
      svg.appendChild(svgEl('text', {
        x: margin.left + plotW / 2, y: height - 10, 'text-anchor': 'middle',
        'font-size': 11.5, fill: p.inkSoft, text: spec.xLabel,
      }));
    }
    if (spec.yLabel) {
      svg.appendChild(svgEl('text', {
        x: 14, y: margin.top + plotH / 2, 'font-size': 11.5, fill: p.inkSoft,
        'text-anchor': 'middle', transform: 'rotate(-90 14 ' +
          (margin.top + plotH / 2) + ')', text: spec.yLabel,
      }));
    }

    var plot = svgEl('g');
    svg.appendChild(plot);
    return {
      svg: svg, plot: plot, fx: fx, fy: fy, palette: p,
      width: width, height: height, margin: margin, plotW: plotW, plotH: plotH,
    };
  }

  function tickLabel(t) {
    var v = t.value === undefined ? t : t.value;
    if (v === 0) return '0';
    var abs = Math.abs(v);
    if (abs >= 10000) return S.thousands(v, 0);
    if (abs >= 10) return String(Math.round(v * 100) / 100);
    if (abs >= 1) return String(Math.round(v * 100) / 100);
    return String(Math.round(v * 1000) / 1000);
  }

  function linTicks(domain, count) {
    var lo = domain[0], hi = domain[1];
    if (!(hi > lo)) return [lo];
    var raw = (hi - lo) / (count || 6);
    var mag = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10));
    var norm = raw / mag;
    var step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
    var ticks = [];
    for (var v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) {
      ticks.push(Math.round(v / step) * step);
    }
    return ticks;
  }

  function logTicks(domain) {
    var lo = Math.max(domain[0], 1e-12), hi = domain[1];
    var ticks = [];
    var start = Math.floor(Math.log(lo) / Math.LN10);
    var end = Math.ceil(Math.log(hi) / Math.LN10);
    for (var e = start; e <= end; e++) {
      [1, 2, 5].forEach(function (m) {
        var v = m * Math.pow(10, e);
        if (v >= lo * 0.999 && v <= hi * 1.001) ticks.push(v);
      });
    }
    if (ticks.length > 12) {
      ticks = ticks.filter(function (v) {
        var r = Math.log(v) / Math.LN10;
        return Math.abs(r - Math.round(r)) < 1e-9;
      });
    }
    return ticks;
  }

  function padDomain(values, logScale, pad) {
    var xs = values.filter(function (v) {
      return typeof v === 'number' && isFinite(v) && (!logScale || v > 0);
    });
    if (!xs.length) return logScale ? [1, 10] : [0, 1];
    var lo = Math.min.apply(null, xs), hi = Math.max.apply(null, xs);
    var f = pad === undefined ? 0.06 : pad;
    if (logScale) {
      var span = Math.log(hi / lo) || Math.LN10;
      return [lo * Math.exp(-span * f), hi * Math.exp(span * f)];
    }
    if (hi === lo) { var d = Math.abs(hi) * 0.1 || 1; return [lo - d, hi + d]; }
    var range = hi - lo;
    return [lo - range * f, hi + range * f];
  }

  function polyline(points, attrs) {
    return svgEl('path', Object.assign({
      d: points.map(function (pt, i) {
        return (i ? 'L' : 'M') + pt[0].toFixed(2) + ' ' + pt[1].toFixed(2);
      }).join(' '),
      fill: 'none', 'stroke-linejoin': 'round', 'stroke-linecap': 'round',
    }, attrs));
  }

  /* Marks carry a 2px surface ring so overlapping points stay countable. */
  function marker(x, y, kind, colour, ring, size) {
    var r = size || 4.5;
    if (kind === 'square') {
      return svgEl('rect', {
        x: x - r, y: y - r, width: 2 * r, height: 2 * r, fill: colour,
        stroke: ring, 'stroke-width': 1.6, rx: 1,
      });
    }
    if (kind === 'triangle') {
      return svgEl('path', {
        d: 'M' + x + ' ' + (y - r * 1.2) + 'L' + (x + r * 1.1) + ' ' + (y + r * 0.8) +
           'L' + (x - r * 1.1) + ' ' + (y + r * 0.8) + 'Z',
        fill: colour, stroke: ring, 'stroke-width': 1.6, 'stroke-linejoin': 'round',
      });
    }
    if (kind === 'diamond') {
      return svgEl('path', {
        d: 'M' + x + ' ' + (y - r * 1.25) + 'L' + (x + r * 1.15) + ' ' + y +
           'L' + x + ' ' + (y + r * 1.25) + 'L' + (x - r * 1.15) + ' ' + y + 'Z',
        fill: colour, stroke: ring, 'stroke-width': 1.6, 'stroke-linejoin': 'round',
      });
    }
    return svgEl('circle', {
      cx: x, cy: y, r: r, fill: colour, stroke: ring, 'stroke-width': 1.6,
    });
  }

  /* A legend is always present for two or more series, so identity never
   * rests on colour alone. */
  /* Pick the corner of the plot holding the fewest marks, so the legend never
   * lands on the data. Falls back to top-left when nothing is passed. */
  function freeCorner(f, points, boxW, boxH) {
    var corners = [
      { x: f.margin.left + 10, y: f.margin.top + 12, cx: 0, cy: 0 },
      { x: f.margin.left + f.plotW - boxW - 4, y: f.margin.top + 12, cx: 1, cy: 0 },
      { x: f.margin.left + 10, y: f.margin.top + f.plotH - boxH + 6, cx: 0, cy: 1 },
      { x: f.margin.left + f.plotW - boxW - 4,
        y: f.margin.top + f.plotH - boxH + 6, cx: 1, cy: 1 },
    ];
    if (!points || !points.length) return corners[0];
    var best = null;
    corners.forEach(function (corner) {
      var x0 = corner.x - 10, x1 = x0 + boxW + 14;
      var y0 = corner.y - 16, y1 = y0 + boxH + 8;
      var hits = 0;
      points.forEach(function (pt) {
        if (pt.px >= x0 && pt.px <= x1 && pt.py >= y0 && pt.py <= y1) hits += 1;
      });
      if (!best || hits < best.hits) best = { corner: corner, hits: hits };
    });
    return best.corner;
  }

  function legend(f, entries, options) {
    var opts = options || {};
    var g = svgEl('g');
    var x, y;
    if (opts.avoid) {
      var widest0 = Math.max.apply(null, entries.map(function (e) {
        return String(e.label).length;
      }));
      var spot = freeCorner(f, opts.avoid, 30 + widest0 * 6.1 + 7,
        entries.length * 17 + 6);
      x = spot.x; y = spot.y;
    } else {
      x = opts.x === undefined ? f.margin.left + 10 : opts.x;
      y = opts.y === undefined ? f.margin.top + 12 : opts.y;
    }
    var pad = 7;
    var box = svgEl('rect', {
      x: x - pad, y: y - 13, rx: 4, fill: f.palette.surface,
      stroke: f.palette.grid, 'stroke-width': 1, 'fill-opacity': 0.92,
    });
    g.appendChild(box);
    var widest = 0;
    entries.forEach(function (entry, i) {
      var ly = y + i * 17;
      if (entry.kind === 'line') {
        g.appendChild(svgEl('line', {
          x1: x, y1: ly - 4, x2: x + 16, y2: ly - 4, stroke: entry.colour,
          'stroke-width': 2, 'stroke-dasharray': entry.dash || null,
        }));
      } else {
        g.appendChild(marker(x + 8, ly - 4, entry.kind || 'circle', entry.colour,
          f.palette.surface));
      }
      g.appendChild(svgEl('text', {
        x: x + 22, y: ly, 'font-size': 11, fill: f.palette.inkSoft, text: entry.label,
      }));
      widest = Math.max(widest, String(entry.label).length);
    });
    box.setAttribute('width', 30 + widest * 6.1 + pad);
    box.setAttribute('height', entries.length * 17 + 6);
    f.svg.appendChild(g);
    return g;
  }

  /* Crosshair and tooltip. An SVG chart on a page is interactive by default;
   * only the static exports skip it. */
  function addHover(f, series, options) {
    var opts = options || {};
    var p = f.palette;
    var layer = svgEl('g', { 'pointer-events': 'none', opacity: 0 });
    var vline = svgEl('line', {
      y1: f.margin.top, y2: f.margin.top + f.plotH, stroke: p.axis,
      'stroke-width': 1, 'stroke-dasharray': '3 3',
    });
    var dot = svgEl('circle', { r: 5, fill: 'none', stroke: p.ink, 'stroke-width': 2 });
    var box = svgEl('rect', {
      rx: 4, fill: p.surface, stroke: p.axis, 'stroke-width': 1, 'fill-opacity': 0.97,
    });
    var text1 = svgEl('text', { 'font-size': 11.5, 'font-weight': 600, fill: p.ink });
    var text2 = svgEl('text', { 'font-size': 11, fill: p.inkSoft });
    layer.appendChild(vline); layer.appendChild(dot);
    layer.appendChild(box); layer.appendChild(text1); layer.appendChild(text2);
    f.svg.appendChild(layer);

    var hit = svgEl('rect', {
      x: f.margin.left, y: f.margin.top, width: f.plotW, height: f.plotH,
      fill: 'transparent',
    });
    f.svg.appendChild(hit);

    function move(event) {
      var pt = f.svg.createSVGPoint();
      pt.x = event.clientX; pt.y = event.clientY;
      var local = pt.matrixTransform(f.svg.getScreenCTM().inverse());
      var best = null;
      series.forEach(function (s) {
        s.points.forEach(function (point) {
          var d = Math.abs(point.px - local.x);
          if (!best || d < best.d) best = { d: d, point: point, series: s };
        });
      });
      if (!best || best.d > 40) { layer.setAttribute('opacity', 0); return; }
      layer.setAttribute('opacity', 1);
      vline.setAttribute('x1', best.point.px);
      vline.setAttribute('x2', best.point.px);
      dot.setAttribute('cx', best.point.px);
      dot.setAttribute('cy', best.point.py);
      text1.textContent = best.series.label;
      text2.textContent = (opts.format || defaultFormat)(best.point, best.series);
      var w = Math.max(text1.textContent.length, text2.textContent.length) * 6.3 + 18;
      var bx = Math.min(best.point.px + 12, f.margin.left + f.plotW - w);
      var by = Math.max(best.point.py - 38, f.margin.top + 2);
      box.setAttribute('x', bx); box.setAttribute('y', by);
      box.setAttribute('width', w); box.setAttribute('height', 36);
      text1.setAttribute('x', bx + 9); text1.setAttribute('y', by + 15);
      text2.setAttribute('x', bx + 9); text2.setAttribute('y', by + 29);
    }
    hit.addEventListener('mousemove', move);
    hit.addEventListener('mouseleave', function () { layer.setAttribute('opacity', 0); });
    /* the tooltip is decoration for export */
    layer.setAttribute('data-export', 'skip');
    hit.setAttribute('data-export', 'skip');
  }

  function defaultFormat(point) {
    return S.sig(point.x, 3) + ', ' + S.sig(point.y, 3);
  }

  /* ============================================================ VES figures */

  /* Sounding curve: measured points, the model response and, on a second
   * axis-free overlay, the layered model as a depth-resistivity staircase. */
  function vesCurve(result, options) {
    var opts = options || {};
    var ab2 = result.ab2, obs = result.rho_obs, calc = result.rho_calc;
    var f = frame({
      width: opts.width || 720, height: opts.height || 430,
      title: opts.title || ('Sounding curve - ' + (result.model.sounding_id || 'VES')),
      xLabel: 'AB/2 (m)', yLabel: 'Apparent resistivity (ohm-m)',
      xLog: true, yLog: true,
      xDomain: padDomain(ab2, true), yDomain: padDomain(obs.concat(calc), true),
    });
    var p = f.palette;

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
    ], { avoid: points });

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
    var f = frame({
      width: opts.width || 340, height: opts.height || 430,
      margin: { top: 30, right: 22, bottom: 56, left: 56 },
      title: opts.title || 'Layered model',
      xLabel: 'Resistivity (ohm-m)', yLabel: 'Depth (m)',
      xLog: true, yDown: true,
      xDomain: padDomain(rho, true, 0.12), yDomain: [0, maxDepth],
    });
    var p = f.palette;

    var pts = [], depth = 0;
    rho.forEach(function (r, i) {
      var top = depth;
      var base = i < h.length ? depth + h[i] : maxDepth;
      pts.push([f.fx(r), f.fy(top)]);
      pts.push([f.fx(r), f.fy(Math.min(base, maxDepth))]);
      depth = base;
    });
    f.plot.appendChild(polyline(pts, { stroke: p.secondary, 'stroke-width': 2.2 }));

    depth = 0;
    rho.forEach(function (r, i) {
      var top = depth;
      var base = i < h.length ? depth + h[i] : maxDepth;
      var mid = f.fy((top + Math.min(base, maxDepth)) / 2);
      var lx = f.fx(r);
      var flip = lx > f.margin.left + f.plotW * 0.55;
      f.plot.appendChild(svgEl('text', {
        x: flip ? lx - 8 : lx + 8, y: mid + 4, 'font-size': 10.5,
        'text-anchor': flip ? 'end' : 'start', fill: p.inkSoft,
        text: C.fmtNum(r, 3) + ' Ω·m',
      }));
      if (i < h.length) {
        f.plot.appendChild(svgEl('line', {
          x1: f.margin.left, y1: f.fy(base), x2: f.margin.left + f.plotW, y2: f.fy(base),
          stroke: p.axis, 'stroke-width': 1, 'stroke-dasharray': '4 3',
        }));
      }
      depth = base;
    });
    return f.svg;
  }

  /* ====================================================== pumping test figures */

  function testOverview(test, analysis, options) {
    var opts = options || {};
    var swl = test.static_water_level_m;
    var allT = [], allWl = [];
    (test.steps || []).forEach(function (s) {
      allT = allT.concat(s.time_min); allWl = allWl.concat(s.water_level_m);
    });
    var recT = test.recovery_time_min || [];
    var duration = test.pumping_duration_min || (allT.length ? Math.max.apply(null, allT) : 0);
    var recShift = recT.map(function (t) { return duration + t; });
    var recWl = test.recovery_level_m || [];

    var f = frame({
      width: opts.width || 760, height: opts.height || 420,
      title: opts.title || 'Pumping test overview',
      xLabel: 'Time since start (min)', yLabel: 'Water level below datum (m)',
      yDown: true,
      xDomain: [0, Math.max.apply(null, [1].concat(allT, recShift)) * 1.02],
      yDomain: padDomain((swl !== null ? [swl] : []).concat(allWl, recWl), false, 0.08),
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

    var series = [], entries = [];
    (test.steps || []).forEach(function (step, i) {
      var pts = step.time_min.map(function (t, k) {
        return { px: f.fx(t), py: f.fy(step.water_level_m[k]), x: t, y: step.water_level_m[k] };
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
    var xLo = f.fx.domainLo, dom = padDomain(t.concat([cj.intercept_t0_min]), true);
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

  function recoveryPlot(analysis, options) {
    var opts = options || {};
    var rec = analysis.recovery;
    if (!rec) return null;
    var test = analysis.test, swl = test.static_water_level_m;
    var tp = test.recovery_time_min || [], levels = test.recovery_level_m || [];
    var ratio = [], residual = [];
    tp.forEach(function (v, i) {
      if (v > 0) {
        ratio.push((test.pumping_duration_min + v) / v);
        residual.push(levels[i] - swl);
      }
    });

    var f = frame({
      width: opts.width || 720, height: opts.height || 400,
      title: opts.title || 'Theis recovery',
      xLabel: "t / t' (log scale)", yLabel: "Residual drawdown s' (m)",
      xLog: true, yDown: true,
      xDomain: padDomain(ratio.concat([1]), true),
      yDomain: padDomain([0].concat(residual), false, 0.1),
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
    legend(f, [
      { label: 'Residual drawdown', kind: 'circle', colour: p.accent },
      { label: 'Fitted line', kind: 'line', colour: p.secondary },
    ], { avoid: pts });
    f.svg.appendChild(svgEl('text', {
      x: f.width - f.margin.right, y: 18, 'text-anchor': 'end',
      'font-size': 11.5, fill: p.inkSoft,
      text: 'T = ' + S.sig(rec.transmissivity_m2_per_day, 3) + ' m²/day · r² = ' +
        rec.r_squared.toFixed(3),
    }));
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

    var f = frame({
      width: opts.width || 620, height: opts.height || 400,
      title: opts.title || 'Step drawdown analysis (Hantush-Bierschenk)',
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
        S.sig(st.well_loss_C, 3) + ' · r² = ' + st.r_squared.toFixed(3),
    }));
    return f.svg;
  }

  /* =================================================== water quality figures */

  var SQ3 = Math.sqrt(3.0);

  function piper(samples, options) {
    var opts = options || {};
    var size = 200, gap = 36;
    var width = opts.width || 720;
    var height = opts.height || 560;
    var p = palette();
    var svg = svgEl('svg', {
      viewBox: '0 0 ' + width + ' ' + height, width: '100%', xmlns: NS,
      'font-family': FONT, role: 'img', 'aria-label': 'Piper diagram',
    });
    svg.appendChild(svgEl('rect', { width: width, height: height, fill: p.surface }));

    /* origin of the whole construction, chosen so the diamond fits above */
    var ox = (width - (2 * size + gap)) / 2;
    var oy = height - 60;
    function place(pt) { return { x: ox + pt.x * size, y: oy - pt.y * size }; }

    function triangle(originX, labels) {
      var g = svgEl('g');
      var x0 = ox + originX * size, y0 = oy;
      var verts = [[x0, y0], [x0 + size, y0],
        [x0 + 0.5 * size, y0 - SQ3 / 2 * size], [x0, y0]];
      [0.2, 0.4, 0.6, 0.8].forEach(function (frac) {
        g.appendChild(svgEl('line', {
          x1: x0 + frac * size, y1: y0,
          x2: x0 + 0.5 * size + 0.5 * frac * size, y2: y0 - SQ3 / 2 * size * (1 - frac),
          stroke: p.grid, 'stroke-width': 0.8,
        }));
        g.appendChild(svgEl('line', {
          x1: x0 + (1 - frac) * size, y1: y0,
          x2: x0 + 0.5 * size - 0.5 * frac * size, y2: y0 - SQ3 / 2 * size * (1 - frac),
          stroke: p.grid, 'stroke-width': 0.8,
        }));
        g.appendChild(svgEl('line', {
          x1: x0 + 0.5 * frac * size, y1: y0 - SQ3 / 2 * size * frac,
          x2: x0 + size - 0.5 * frac * size, y2: y0 - SQ3 / 2 * size * frac,
          stroke: p.grid, 'stroke-width': 0.8,
        }));
      });
      g.appendChild(polyline(verts, { stroke: p.neutral, 'stroke-width': 1.3 }));
      g.appendChild(svgEl('text', { x: x0 - 6, y: y0 + 15, 'text-anchor': 'end',
        'font-size': 11, fill: p.inkSoft, text: labels[0] }));
      g.appendChild(svgEl('text', { x: x0 + size + 6, y: y0 + 15, 'text-anchor': 'start',
        'font-size': 11, fill: p.inkSoft, text: labels[1] }));
      g.appendChild(svgEl('text', { x: x0 + 0.5 * size, y: y0 - SQ3 / 2 * size - 8,
        'text-anchor': 'middle', 'font-size': 11, fill: p.inkSoft, text: labels[2] }));
      svg.appendChild(g);
    }

    triangle(0, ['Ca', 'Na+K', 'Mg']);
    triangle(1 + gap / size, ['HCO₃', 'Cl', 'SO₄']);

    /* the diamond, from the projection geometry */
    var xMid = 1 + gap / size / 2;
    var yBot = SQ3 / 2.0 * (gap / size);
    var diamond = [
      { x: xMid, y: yBot },
      { x: xMid + 0.5, y: yBot + SQ3 / 2 },
      { x: xMid, y: yBot + SQ3 },
      { x: xMid - 0.5, y: yBot + SQ3 / 2 },
      { x: xMid, y: yBot },
    ].map(place);
    svg.appendChild(polyline(diamond.map(function (d) { return [d.x, d.y]; }),
      { stroke: p.neutral, 'stroke-width': 1.3 }));
    svg.appendChild(svgEl('text', {
      x: ox + xMid * size, y: oy - (yBot + SQ3) * size - 10, 'text-anchor': 'middle',
      'font-size': 10, fill: p.muted,
      text: 'SO₄ + Cl increases upward; Na + K increases to the right',
    }));

    var kinds = ['circle', 'square', 'triangle', 'diamond'];
    var entries = [];
    (samples || []).forEach(function (sample, i) {
      var pts = C.piperPoints(sample, { size: 1.0, gap: gap / size });
      if (!pts) return;
      var colour = p.cat[i % 3];   /* three slots validate for scatter overlap */
      var kind = kinds[i % kinds.length];
      var label = sample.sample_id || (sample.site && sample.site.community) ||
        ('sample ' + (i + 1));
      [pts.cation, pts.anion, pts.diamond].forEach(function (pt) {
        var q = place(pt);
        svg.appendChild(marker(q.x, q.y, kind, colour, p.surface, 5));
      });
      entries.push({ label: label + (pts.facies ? ' — ' + pts.facies : ''),
        kind: kind, colour: colour });
    });

    if (entries.length) {
      var lg = svgEl('g');
      var lx = 16, ly = 24;
      lg.appendChild(svgEl('rect', {
        x: lx - 8, y: ly - 14, rx: 4, fill: p.surface, stroke: p.grid,
        'stroke-width': 1, 'fill-opacity': 0.94,
        width: 24 + Math.max.apply(null, entries.map(function (e) {
          return e.label.length;
        })) * 6.1, height: entries.length * 17 + 6,
      }));
      entries.forEach(function (e, i) {
        lg.appendChild(marker(lx + 6, ly + i * 17 - 4, e.kind, e.colour, p.surface, 4.5));
        lg.appendChild(svgEl('text', { x: lx + 18, y: ly + i * 17,
          'font-size': 11, fill: p.inkSoft, text: e.label }));
      });
      svg.appendChild(lg);
    }
    if (opts.title !== null) {
      svg.appendChild(svgEl('text', {
        x: 16, y: height - 12, 'font-size': 13, 'font-weight': 600, fill: p.ink,
        text: opts.title || 'Piper diagram',
      }));
    }
    return svg;
  }

  function stiff(sample, options) {
    var opts = options || {};
    var rows = C.stiffRows(sample);
    if (!rows) return null;
    var width = opts.width || 460, height = opts.height || 250;
    var p = palette();
    var svg = svgEl('svg', {
      viewBox: '0 0 ' + width + ' ' + height, width: '100%', xmlns: NS,
      'font-family': FONT, role: 'img', 'aria-label': 'Stiff diagram',
    });
    svg.appendChild(svgEl('rect', { width: width, height: height, fill: p.surface }));

    var span = Math.max(
      Math.max.apply(null, rows.map(function (r) { return r.left; })),
      Math.max.apply(null, rows.map(function (r) { return r.right; })), 0.5) * 1.3;
    var cx = width / 2, top = 52, rowH = 44;
    function fx(meq) { return cx + (meq / span) * (width / 2 - 60); }
    function fy(i) { return top + i * rowH; }

    /* axis ticks so the polygon can be read as numbers, not just a shape */
    var ticks = linTicks([0, span], 3).filter(function (v) { return v > 0; });
    ticks.forEach(function (v) {
      [-1, 1].forEach(function (sign) {
        var x = fx(sign * v);
        svg.appendChild(svgEl('line', {
          x1: x, y1: top - 12, x2: x, y2: fy(rows.length - 1) + 12,
          stroke: p.grid, 'stroke-width': 1,
        }));
        svg.appendChild(svgEl('text', {
          x: x, y: fy(rows.length - 1) + 26, 'text-anchor': 'middle',
          'font-size': 10, fill: p.muted, text: String(v),
        }));
      });
    });

    var poly = rows.map(function (r, i) { return [fx(-r.left), fy(i)]; })
      .concat(rows.map(function (r, i) {
        return [fx(rows[rows.length - 1 - i].right), fy(rows.length - 1 - i)];
      }));
    svg.appendChild(svgEl('path', {
      d: poly.map(function (pt, i) {
        return (i ? 'L' : 'M') + pt[0].toFixed(1) + ' ' + pt[1].toFixed(1);
      }).join(' ') + ' Z',
      fill: p.accent, 'fill-opacity': 0.22, stroke: p.accent, 'stroke-width': 1.8,
      'stroke-linejoin': 'round',
    }));
    svg.appendChild(svgEl('line', {
      x1: cx, y1: top - 12, x2: cx, y2: fy(rows.length - 1) + 12,
      stroke: p.neutral, 'stroke-width': 1.2,
    }));

    rows.forEach(function (r, i) {
      svg.appendChild(marker(fx(-r.left), fy(i), 'circle', p.accent, p.surface, 3.2));
      svg.appendChild(marker(fx(r.right), fy(i), 'circle', p.accent, p.surface, 3.2));
      svg.appendChild(svgEl('text', { x: 8, y: fy(i) + 4, 'font-size': 11,
        fill: p.inkSoft, text: r.leftLabel }));
      svg.appendChild(svgEl('text', { x: width - 8, y: fy(i) + 4, 'text-anchor': 'end',
        'font-size': 11, fill: p.inkSoft, text: r.rightLabel }));
      /* the numbers themselves, so the figure does not rely on the eye */
      svg.appendChild(svgEl('text', { x: fx(-r.left) - 7, y: fy(i) - 7,
        'text-anchor': 'end', 'font-size': 9.5, fill: p.muted,
        text: r.left.toFixed(2) }));
      svg.appendChild(svgEl('text', { x: fx(r.right) + 7, y: fy(i) - 7,
        'font-size': 9.5, fill: p.muted, text: r.right.toFixed(2) }));
    });

    svg.appendChild(svgEl('text', {
      x: cx, y: height - 8, 'text-anchor': 'middle', 'font-size': 10.5,
      fill: p.muted, text: 'meq/L — cations left, anions right',
    }));
    svg.appendChild(svgEl('text', {
      x: 12, y: 22, 'font-size': 13, 'font-weight': 600, fill: p.ink,
      text: opts.title || ('Stiff diagram — ' + (sample.sample_id ||
        (sample.site && sample.site.community) || 'sample')),
    }));
    return svg;
  }

  /* =================================================== borehole design drawing */

  /* Lithology fills. Each is paired with a label in the legend, so the pattern
   * is a cue and never the only carrier of meaning. */
  var LITHOLOGY_COLOURS = [
    [/laterite|duricrust|topsoil/i, '#B5651D'],
    [/clay|saprolite/i, '#9E8B5F'],
    [/sand|gravel/i, '#D9C89A'],
    [/weather|regolith/i, '#A98F63'],
    [/fresh|granite|basement|bedrock|gneiss|schist/i, '#7E7F84'],
    [/fracture/i, '#6D8FA8'],
  ];

  function lithologyColour(description) {
    for (var i = 0; i < LITHOLOGY_COLOURS.length; i++) {
      if (LITHOLOGY_COLOURS[i][0].test(description || '')) return LITHOLOGY_COLOURS[i][1];
    }
    return '#B0A99C';
  }

  /* A to-scale section: depth ruler, lithology column and construction column
   * with the annulus, matching the drawing the .docx report carries. */
  function boreholeDesign(design, log, options) {
    var opts = options || {};
    var p = palette();
    var width = opts.width || 620;
    var height = opts.height || 700;
    var top = 60, bottom = height - 46;
    var depthMax = design.total_depth_m * 1.04;
    function fy(d) { return top + (d / depthMax) * (bottom - top); }

    var svg = svgEl('svg', {
      viewBox: '0 0 ' + width + ' ' + height, width: '100%', xmlns: NS,
      'font-family': FONT, role: 'img', 'aria-label': 'Borehole construction design',
    });
    svg.appendChild(svgEl('rect', { width: width, height: height, fill: p.surface }));
    svg.appendChild(svgEl('text', {
      x: 16, y: 24, 'font-size': 13, 'font-weight': 600, fill: p.ink,
      text: opts.title || 'Borehole construction design',
    }));

    var rulerX = 52;
    var lithX = 74, lithW = 92;
    var holeCx = 300, holeHalf = 52, casingHalf = 26;

    /* depth ruler */
    svg.appendChild(svgEl('line', {
      x1: rulerX, y1: top, x2: rulerX, y2: bottom, stroke: p.axis, 'stroke-width': 1,
    }));
    var step = depthMax > 80 ? 10 : (depthMax > 30 ? 5 : 2);
    for (var d = 0; d <= design.total_depth_m + 1e-9; d += step) {
      var y = fy(d);
      svg.appendChild(svgEl('line', {
        x1: rulerX - 5, y1: y, x2: rulerX, y2: y, stroke: p.axis, 'stroke-width': 1,
      }));
      svg.appendChild(svgEl('text', {
        x: rulerX - 9, y: y + 4, 'text-anchor': 'end', 'font-size': 10,
        fill: p.muted, text: String(Math.round(d)),
      }));
    }
    svg.appendChild(svgEl('text', {
      x: rulerX - 9, y: top - 10, 'text-anchor': 'end', 'font-size': 10,
      fill: p.muted, text: 'depth (m)',
    }));

    /* lithology column */
    var litho = (log && log.intervals) || [];
    var seen = [];
    litho.forEach(function (interval) {
      var colour = lithologyColour(interval.description);
      var y0 = fy(interval.top_m), y1 = fy(Math.min(interval.bottom_m, design.total_depth_m));
      svg.appendChild(svgEl('rect', {
        x: lithX, y: y0, width: lithW, height: Math.max(1, y1 - y0),
        fill: colour, stroke: p.surface, 'stroke-width': 1,
      }));
      if (y1 - y0 > 13) {
        svg.appendChild(svgEl('text', {
          x: lithX + lithW / 2, y: (y0 + y1) / 2 + 3.5, 'text-anchor': 'middle',
          'font-size': 9, fill: '#FFFFFF',
          text: String(interval.description || '').split(/[,;]/)[0].slice(0, 16),
        }));
      }
      var key = String(interval.description || '').split(/[,;]/)[0];
      if (key && !seen.some(function (s) { return s.label === key; })) {
        seen.push({ label: key, colour: colour });
      }
    });
    if (!litho.length) {
      svg.appendChild(svgEl('rect', {
        x: lithX, y: top, width: lithW, height: bottom - top,
        fill: '#D8D4CB', stroke: p.axis, 'stroke-width': 1,
      }));
      svg.appendChild(svgEl('text', {
        x: lithX + lithW / 2, y: (top + bottom) / 2, 'text-anchor': 'middle',
        'font-size': 10, fill: p.muted, text: 'no log',
      }));
    }
    svg.appendChild(svgEl('text', {
      x: lithX + lithW / 2, y: top - 10, 'text-anchor': 'middle', 'font-size': 10,
      fill: p.muted, text: 'lithology',
    }));

    /* annulus: gravel pack, backfill and sanitary seal */
    function annulus(fromM, toM, fill, pattern) {
      var y0 = fy(fromM), y1 = fy(toM);
      if (y1 <= y0) return;
      [-1, 1].forEach(function (side) {
        var x = side < 0 ? holeCx - holeHalf : holeCx + casingHalf;
        svg.appendChild(svgEl('rect', {
          x: x, y: y0, width: holeHalf - casingHalf, height: y1 - y0,
          fill: fill, stroke: p.axis, 'stroke-width': 0.7,
        }));
      });
    }
    annulus(design.gravel_pack[0], design.gravel_pack[1], '#D9C89A');
    annulus(design.backfill[0], design.backfill[1], '#C9C4B6');
    annulus(design.sanitary_seal[0], design.sanitary_seal[1], '#9BA3A8');

    /* borehole wall */
    [-1, 1].forEach(function (side) {
      var x = holeCx + side * holeHalf;
      svg.appendChild(svgEl('line', {
        x1: x, y1: fy(0), x2: x, y2: fy(design.total_depth_m),
        stroke: p.neutral, 'stroke-width': 1.4,
      }));
    });
    svg.appendChild(svgEl('line', {
      x1: holeCx - holeHalf, y1: fy(design.total_depth_m),
      x2: holeCx + holeHalf, y2: fy(design.total_depth_m),
      stroke: p.neutral, 'stroke-width': 1.4,
    }));

    /* casing string */
    design.segments.forEach(function (seg) {
      var y0 = fy(seg.top_m), y1 = fy(seg.bottom_m);
      var fill = seg.kind === 'screen' ? p.accent
        : (seg.kind === 'sump' ? '#7E8B92' : '#E8E6E0');
      [-1, 1].forEach(function (side) {
        var x = side < 0 ? holeCx - casingHalf : holeCx + casingHalf - 9;
        svg.appendChild(svgEl('rect', {
          x: x, y: y0, width: 9, height: Math.max(1, y1 - y0),
          fill: fill, stroke: p.neutral, 'stroke-width': 0.8,
        }));
        if (seg.kind === 'screen') {
          /* slot hatching, so a screen reads as a screen in monochrome print */
          for (var sy = y0 + 3; sy < y1 - 2; sy += 5) {
            svg.appendChild(svgEl('line', {
              x1: x + 1, y1: sy, x2: x + 8, y2: sy,
              stroke: p.surface, 'stroke-width': 1.1,
            }));
          }
        }
      });
      /* label to the right, with a leader */
      var midY = (y0 + y1) / 2;
      if (y1 - y0 > 11 || seg.kind === 'screen') {
        var labelX = holeCx + holeHalf + 16;
        svg.appendChild(svgEl('line', {
          x1: holeCx + holeHalf + 2, y1: midY, x2: labelX - 4, y2: midY,
          stroke: p.axis, 'stroke-width': 0.8,
        }));
        svg.appendChild(svgEl('text', {
          x: labelX, y: midY + 3.5, 'font-size': 10, fill: p.inkSoft,
          text: (seg.kind === 'screen' ? 'Screen ' : seg.kind === 'sump' ? 'Sump ' : 'Plain casing ') +
            seg.top_m.toFixed(1) + '–' + seg.bottom_m.toFixed(1) + ' m',
        }));
      }
    });

    /* stick-up and apron */
    svg.appendChild(svgEl('rect', {
      x: holeCx - casingHalf, y: fy(0) - 14, width: 2 * casingHalf, height: 14,
      fill: '#E8E6E0', stroke: p.neutral, 'stroke-width': 0.8,
    }));
    svg.appendChild(svgEl('rect', {
      x: holeCx - holeHalf - 22, y: fy(0) - 5, width: 2 * (holeHalf + 22), height: 6,
      fill: '#B9B7AF', stroke: p.neutral, 'stroke-width': 0.8,
    }));
    svg.appendChild(svgEl('text', {
      x: holeCx + holeHalf + 30, y: fy(0) - 8, 'font-size': 10, fill: p.inkSoft,
      text: 'stick-up ' + design.stickup_m.toFixed(1) + ' m, ' +
        design.casing_diameter_in + '" ' + design.casing_material,
    }));

    /* static water level and pump intake */
    if (design.static_water_level_m !== null && design.static_water_level_m !== undefined) {
      var swlY = fy(design.static_water_level_m);
      svg.appendChild(svgEl('line', {
        x1: holeCx - holeHalf - 26, y1: swlY, x2: holeCx + holeHalf + 8, y2: swlY,
        stroke: p.cat[0], 'stroke-width': 1.6, 'stroke-dasharray': '6 3',
      }));
      svg.appendChild(svgEl('text', {
        x: holeCx - holeHalf - 30, y: swlY - 4, 'text-anchor': 'end',
        'font-size': 10, fill: p.cat[0],
        text: 'SWL ' + design.static_water_level_m.toFixed(2) + ' m',
      }));
    }
    (design.water_strikes_m || []).forEach(function (strike) {
      var sy = fy(strike);
      svg.appendChild(svgEl('path', {
        d: 'M' + (holeCx - holeHalf - 12) + ' ' + sy + 'l-9 -5v10z',
        fill: p.secondary,
      }));
      svg.appendChild(svgEl('text', {
        x: holeCx - holeHalf - 26, y: sy + 3.5, 'text-anchor': 'end',
        'font-size': 9.5, fill: p.secondary, text: strike + ' m strike',
      }));
    });
    if (design.pump_intake_m !== null && design.pump_intake_m !== undefined) {
      var py = fy(design.pump_intake_m);
      svg.appendChild(svgEl('rect', {
        x: holeCx - 8, y: py - 9, width: 16, height: 18, rx: 2,
        fill: p.neutral, stroke: p.surface, 'stroke-width': 1,
      }));
      svg.appendChild(svgEl('text', {
        x: holeCx + holeHalf + 16, y: py + 3.5, 'font-size': 10, fill: p.inkSoft,
        text: 'pump intake ' + design.pump_intake_m.toFixed(0) + ' m',
      }));
    }

    /* legend for the annulus and lithology fills */
    var legendItems = [
      { label: 'Gravel pack', colour: '#D9C89A' },
      { label: 'Backfill', colour: '#C9C4B6' },
      { label: 'Cement seal', colour: '#9BA3A8' },
      { label: 'Screen', colour: p.accent },
    ].concat(seen.slice(0, 4));
    var lx = 16, ly = height - 26;
    legendItems.forEach(function (item, i) {
      var col = i % 4, row = Math.floor(i / 4);
      var x = lx + col * 148, y = ly + row * 15 - 15;
      svg.appendChild(svgEl('rect', {
        x: x, y: y - 8, width: 11, height: 11, fill: item.colour,
        stroke: p.axis, 'stroke-width': 0.6, rx: 1.5,
      }));
      svg.appendChild(svgEl('text', {
        x: x + 16, y: y + 1, 'font-size': 9.5, fill: p.inkSoft,
        text: String(item.label).slice(0, 20),
      }));
    });
    return svg;
  }

  /* ========================================================= costing figures */

  /* ------------------------------------------------------------ depth spine
   *
   * The whole borehole on one depth axis: the cuttings log, the casing string
   * and the water levels registered against the same ruler.
   *
   * There is one depth-to-pixel mapping and every column calls it, which is
   * what makes the alignment true rather than drawn - a screen that misses a
   * water strike cannot be rendered as though it hits one. The screened
   * intervals carry drag handles; everything else is evidence.
   */
  function depthSpine(view, options) {
    var opts = options || {};
    var p = palette();
    var section = view.section;
    var width = opts.width || 720;
    var height = opts.height || 620;
    var top = 64, bottom = height - 34;
    var domain = section.domain || section.totalDepth * 1.06;
    function fy(d) { return top + (d / domain) * (bottom - top); }
    function fh(a, b) { return Math.max(1, (b - a) / domain * (bottom - top)); }
    /* pixels back to metres, for the pointer */
    var perMetre = (bottom - top) / domain;

    var svg = svgEl('svg', {
      viewBox: '0 0 ' + width + ' ' + height, width: '100%', xmlns: NS,
      'font-family': FONT, role: 'img',
      'aria-label': 'The borehole on one depth axis',
      style: 'touch-action:none',
    });
    svg.appendChild(svgEl('rect', { width: width, height: height, fill: p.surface }));
    svg.appendChild(svgEl('text', {
      x: 16, y: 24, 'font-size': 13, 'font-weight': 600, fill: p.ink,
      text: opts.title || 'Depth spine',
    }));

    var rulerX = 46;
    var lithX = 66, lithW = 150;
    var holeCx = 320, holeHalf = 46, casingHalf = 22;
    var hydroX = 402;

    function columnHead(x, label, anchor) {
      svg.appendChild(svgEl('text', {
        x: x, y: top - 12, 'font-size': 10, fill: p.muted,
        'text-anchor': anchor || 'middle', text: label,
      }));
    }

    /* --- the shared ruler --------------------------------------------- */
    svg.appendChild(svgEl('line', {
      x1: rulerX, y1: top, x2: rulerX, y2: bottom, stroke: p.axis, 'stroke-width': 1,
    }));
    var step = domain > 160 ? 25 : (domain > 80 ? 10 : (domain > 30 ? 5 : 2));
    for (var d = 0; d <= domain; d += step) {
      var ty = fy(d);
      svg.appendChild(svgEl('line', {
        x1: rulerX - 5, y1: ty, x2: width - 12, y2: ty,
        stroke: p.grid, 'stroke-width': 0.6,
      }));
      svg.appendChild(svgEl('text', {
        x: rulerX - 8, y: ty + 3.5, 'text-anchor': 'end', 'font-size': 9.5,
        fill: p.muted, text: String(Math.round(d)),
      }));
    }
    columnHead(rulerX - 8, 'm', 'end');

    /* --- lithology, from the driller's own words ---------------------- */
    columnHead(lithX + lithW / 2, 'Lithology — cuttings');
    (section.lithology || []).forEach(function (unit) {
      var y0 = fy(unit.top), h = fh(unit.top, unit.base);
      var colour = unit.aquifer ? p.accentSoft : lithologyColour(unit.description);
      var block = svgEl('rect', {
        x: lithX, y: y0, width: lithW, height: h,
        fill: colour, stroke: p.surface, 'stroke-width': 1,
      });
      block.appendChild(svgEl('title', {
        text: unit.top + '–' + unit.base + ' m · ' + unit.description,
      }));
      svg.appendChild(block);
      if (h > 12) {
        svg.appendChild(svgEl('text', {
          x: lithX + 6, y: y0 + h / 2 + 3.5, 'font-size': 9,
          fill: unit.aquifer ? p.ink : '#FFFFFF',
          text: String(unit.description || '').split(/[,;]/)[0].slice(0, 26),
        }));
      }
    });
    if (!(section.lithology || []).length) {
      svg.appendChild(svgEl('rect', {
        x: lithX, y: top, width: lithW, height: bottom - top,
        fill: '#D8D4CB', stroke: p.axis, 'stroke-width': 1,
      }));
    }
    (section.waterStrikes || []).forEach(function (strike) {
      var y = fy(strike);
      svg.appendChild(svgEl('line', {
        x1: lithX, y1: y, x2: lithX + lithW, y2: y,
        stroke: p.accent, 'stroke-width': 2, 'stroke-dasharray': '5 3',
      }));
      svg.appendChild(svgEl('text', {
        x: lithX + lithW - 4, y: y - 3, 'text-anchor': 'end', 'font-size': 9,
        fill: p.accent, text: 'strike ' + Number(strike).toFixed(1),
      }));
    });

    /* --- construction: the only editable thing on the section --------- */
    columnHead(holeCx, 'Construction');
    function annulus(band, fill) {
      if (!band || band.length < 2 || band[1] <= band[0]) return;
      [-1, 1].forEach(function (side) {
        svg.appendChild(svgEl('rect', {
          x: side < 0 ? holeCx - holeHalf : holeCx + casingHalf,
          y: fy(band[0]), width: holeHalf - casingHalf, height: fh(band[0], band[1]),
          fill: fill, stroke: p.axis, 'stroke-width': 0.6,
        }));
      });
    }
    annulus(section.backfill, '#C9C4B6');
    annulus(section.gravelPack, '#D9C89A');
    annulus(section.sanitarySeal, '#9BA3A8');

    [-1, 1].forEach(function (side) {
      svg.appendChild(svgEl('line', {
        x1: holeCx + side * holeHalf, y1: fy(0),
        x2: holeCx + side * holeHalf, y2: fy(section.totalDepth),
        stroke: p.neutral, 'stroke-width': 1.3,
      }));
    });

    (section.segments || []).filter(function (s) { return s.kind !== 'screen'; })
      .forEach(function (seg) {
        svg.appendChild(svgEl('rect', {
          x: holeCx - casingHalf, y: fy(seg.top),
          width: casingHalf * 2, height: fh(seg.top, seg.base),
          fill: seg.kind === 'sump' ? '#7E8B92' : '#E8E6E0',
          stroke: p.neutral, 'stroke-width': 0.8,
        }));
      });

    /* the live intervals, so the drawing keeps up with the pointer */
    var screens = opts.screens || (view.design.screens || []).map(function (s) {
      return { top: s.top, base: s.base };
    });
    screens.forEach(function (screen, index) {
      var y0 = fy(screen.top), h = fh(screen.top, screen.base);
      svg.appendChild(svgEl('rect', {
        x: holeCx - casingHalf, y: y0, width: casingHalf * 2, height: h,
        fill: p.accent, stroke: p.neutral, 'stroke-width': 0.8,
        'data-screen': index, 'data-edge': 'body',
        style: opts.readOnly ? '' : 'cursor:grab',
      }));
      for (var slot = y0 + 4; slot < y0 + h - 2; slot += 6) {
        svg.appendChild(svgEl('line', {
          x1: holeCx - casingHalf + 3, y1: slot, x2: holeCx + casingHalf - 3, y2: slot,
          stroke: p.surface, 'stroke-width': 1, 'pointer-events': 'none',
        }));
      }
      if (h > 22) {
        svg.appendChild(svgEl('text', {
          x: holeCx, y: y0 + h / 2 + 3.5, 'text-anchor': 'middle', 'font-size': 9,
          fill: '#FFFFFF', 'pointer-events': 'none',
          text: 'screen ' + (index + 1) + ' · ' +
            (screen.base - screen.top).toFixed(1) + ' m',
        }));
      }
      [['top', screen.top, y0], ['base', screen.base, y0 + h]].forEach(function (edge) {
        if (!opts.readOnly) {
          svg.appendChild(svgEl('rect', {
            x: holeCx - casingHalf - 8, y: edge[2] - 4,
            width: casingHalf * 2 + 16, height: 8,
            fill: p.secondary, opacity: 0.9, rx: 3,
            'data-screen': index, 'data-edge': edge[0],
            tabindex: 0, role: 'slider',
            'aria-label': edge[0] === 'top'
              ? 'Top of screen ' + (index + 1) + ', metres below ground level'
              : 'Base of screen ' + (index + 1) + ', metres below ground level',
            'aria-valuenow': edge[1], 'aria-valuemin': section.screenLimits.top,
            'aria-valuemax': section.screenLimits.base,
            'aria-valuetext': edge[1].toFixed(1) + ' metres',
            style: 'cursor:ns-resize',
          }));
        }
        svg.appendChild(svgEl('text', {
          x: holeCx + casingHalf + 14, y: edge[2] + 3.5, 'font-size': 9,
          fill: p.secondary, 'pointer-events': 'none', text: edge[1].toFixed(1),
        }));
      });
    });

    svg.appendChild(svgEl('line', {
      x1: holeCx - holeHalf - 6, y1: fy(section.totalDepth),
      x2: holeCx + holeHalf + 6, y2: fy(section.totalDepth),
      stroke: p.neutral, 'stroke-width': 1.6,
    }));
    svg.appendChild(svgEl('text', {
      x: holeCx - holeHalf - 6, y: fy(section.totalDepth) + 12, 'font-size': 9,
      fill: p.inkSoft, text: 'TD ' + section.totalDepth.toFixed(1) + ' m',
    }));

    /* --- hydraulics: rest level, the level the test reached, the intake -- */
    columnHead(hydroX + 70, 'Hydraulics');
    var levels = section.levels || {};
    if (levels.restLevel !== undefined) {
      svg.appendChild(svgEl('rect', {
        x: hydroX, y: fy(levels.restLevel), width: 150,
        height: Math.max(1, fy(section.totalDepth) - fy(levels.restLevel)),
        fill: p.accentSoft, opacity: 0.22,
      }));
      svg.appendChild(svgEl('line', {
        x1: hydroX, y1: fy(levels.restLevel), x2: hydroX + 150, y2: fy(levels.restLevel),
        stroke: p.accent, 'stroke-width': 1.6,
      }));
      svg.appendChild(svgEl('text', {
        x: hydroX + 2, y: fy(levels.restLevel) - 4, 'font-size': 9, fill: p.accent,
        text: 'SWL ' + levels.restLevel.toFixed(2) + ' m',
      }));
    }
    if (levels.pumpingLevel !== undefined) {
      svg.appendChild(svgEl('line', {
        x1: hydroX, y1: fy(levels.pumpingLevel),
        x2: hydroX + 150, y2: fy(levels.pumpingLevel),
        stroke: p.secondary, 'stroke-width': 1.6,
        'stroke-dasharray': levels.stabilised ? '' : '5 3',
      }));
      svg.appendChild(svgEl('text', {
        x: hydroX + 2, y: fy(levels.pumpingLevel) + 12, 'font-size': 9,
        fill: p.secondary,
        text: (levels.stabilised ? 'pumping level ' : 'deepest level ') +
          levels.pumpingLevel.toFixed(2) + ' m',
      }));
      if (levels.restLevel !== undefined) {
        var mid = (fy(levels.restLevel) + fy(levels.pumpingLevel)) / 2;
        svg.appendChild(svgEl('line', {
          x1: hydroX + 130, y1: fy(levels.restLevel),
          x2: hydroX + 130, y2: fy(levels.pumpingLevel),
          stroke: p.secondary, 'stroke-width': 1,
        }));
        svg.appendChild(svgEl('text', {
          x: hydroX + 126, y: mid + 3.5, 'text-anchor': 'end', 'font-size': 9,
          fill: p.secondary,
          text: 's = ' + (levels.maxDrawdown !== null && levels.maxDrawdown !== undefined
            ? levels.maxDrawdown : levels.pumpingLevel - levels.restLevel).toFixed(2) + ' m',
        }));
      }
    }
    if (levels.pumpIntake !== undefined) {
      svg.appendChild(svgEl('line', {
        x1: hydroX, y1: fy(levels.pumpIntake), x2: hydroX + 96,
        y2: fy(levels.pumpIntake), stroke: p.ink, 'stroke-width': 1.2,
        'stroke-dasharray': '2 2',
      }));
      svg.appendChild(svgEl('text', {
        x: hydroX + 2, y: fy(levels.pumpIntake) - 4, 'font-size': 9, fill: p.ink,
        text: 'pump intake ' + levels.pumpIntake.toFixed(0) + ' m',
      }));
    }
    if (levels.stabilised === false) {
      svg.appendChild(svgEl('text', {
        x: hydroX, y: bottom + 14, 'font-size': 8.5, fill: p.muted,
        text: 'The level had not stabilised when the test ended.',
      }));
    }

    svg.spineScale = {
      metresPerPixel: 1 / perMetre, depthAt: function (px) { return px / perMetre; },
    };
    return svg;
  }

  /* Every determinand as a multiple of its own binding limit, so one chart
   * carries determinands whose limits differ by four orders of magnitude. */
  function guidelineSpine(rows, options) {
    var opts = options || {};
    var p = palette();
    var judged = (rows || []).filter(function (r) {
      return r.ratio !== null && r.ratio !== undefined && isFinite(r.ratio);
    }).sort(function (a, b) { return b.ratio - a.ratio; });
    if (!judged.length) return null;

    var rowH = 20;
    var width = opts.width || 720;
    var height = 54 + judged.length * rowH;
    var left = 172, right = width - 58;
    var maxRatio = Math.max(2, Math.min(
      8, judged[0].ratio * 1.15));
    function fx(ratio) {
      return left + Math.min(ratio, maxRatio) / maxRatio * (right - left);
    }

    var svg = svgEl('svg', {
      viewBox: '0 0 ' + width + ' ' + height, width: '100%', xmlns: NS,
      'font-family': FONT, role: 'img',
      'aria-label': 'Every determinand as a multiple of its binding limit',
    });
    svg.appendChild(svgEl('rect', { width: width, height: height, fill: p.surface }));

    [0.5, 1, 2].concat(maxRatio > 4 ? [4] : []).forEach(function (tick) {
      if (tick > maxRatio) return;
      svg.appendChild(svgEl('line', {
        x1: fx(tick), y1: 32, x2: fx(tick), y2: height - 16,
        stroke: tick === 1 ? p.critical : p.grid,
        'stroke-width': tick === 1 ? 1.2 : 0.6,
        'stroke-dasharray': tick === 1 ? '' : '3 3',
      }));
      svg.appendChild(svgEl('text', {
        x: fx(tick), y: 26, 'text-anchor': 'middle', 'font-size': 9,
        fill: tick === 1 ? p.critical : p.muted,
        text: tick === 1 ? 'limit' : '×' + tick,
      }));
    });

    judged.forEach(function (row, i) {
      var y = 38 + i * rowH;
      svg.appendChild(svgEl('text', {
        x: left - 8, y: y + 10, 'text-anchor': 'end', 'font-size': 9.5, fill: p.ink,
        text: String(row.parameter).slice(0, 26),
      }));
      var over = row.ratio > 1;
      svg.appendChild(svgEl('rect', {
        x: left, y: y + 3, width: Math.max(1, fx(row.ratio) - left), height: 12,
        rx: 2, fill: over ? p.critical : p.good, opacity: over ? 0.9 : 0.75,
      }));
      svg.appendChild(svgEl('text', {
        x: Math.min(fx(row.ratio) + 5, right + 4), y: y + 13, 'font-size': 9,
        fill: p.inkSoft,
        text: (row.value === null ? '—' : row.value) + ' ' + (row.unit || ''),
      }));
    });
    svg.appendChild(svgEl('text', {
      x: 12, y: height - 4, 'font-size': 8.5, fill: p.muted,
      text: 'Bars past the limit line exceed the strictest applicable value.',
    }));
    return svg;
  }

  function costBreakdown(estimate, options) {
    var opts = options || {};
    var mode = opts.mode || 'stage';
    var data = mode === 'stage' ? estimate.by_stage() : estimate.by_category();
    var p = palette();
    var width = opts.width || 700;
    var barH = 26, gap = 10;
    var height = 62 + data.length * (barH + gap);
    var labelW = 150;
    var total = data.reduce(function (a, d) { return a + d[1]; }, 0);
    var maxV = Math.max.apply(null, data.map(function (d) { return d[1]; }));

    var svg = svgEl('svg', {
      viewBox: '0 0 ' + width + ' ' + height, width: '100%', xmlns: NS,
      'font-family': FONT, role: 'img',
      'aria-label': 'Cost breakdown by ' + mode,
    });
    svg.appendChild(svgEl('rect', { width: width, height: height, fill: p.surface }));
    svg.appendChild(svgEl('text', {
      x: 14, y: 22, 'font-size': 13, 'font-weight': 600, fill: p.ink,
      text: opts.title || ('Direct cost by ' + (mode === 'stage' ? 'construction stage'
        : 'resource category')),
    }));

    var plotW = width - labelW - 96;
    data.forEach(function (row, i) {
      var y = 42 + i * (barH + gap);
      var w = maxV > 0 ? (row[1] / maxV) * plotW : 0;
      svg.appendChild(svgEl('text', {
        x: labelW - 10, y: y + barH / 2 + 4, 'text-anchor': 'end',
        'font-size': 11.5, fill: p.inkSoft,
        text: mode === 'stage' ? row[0] : S.titleCase(row[0]),
      }));
      /* rounded data end anchored to the baseline */
      svg.appendChild(svgEl('path', {
        d: roundedBar(labelW, y, Math.max(w, 2), barH, 4),
        fill: p.cat[i % p.cat.length],
      }));
      svg.appendChild(svgEl('text', {
        x: labelW + w + 10, y: y + barH / 2 + 4, 'font-size': 11.5, fill: p.ink,
        text: S.money(row[1], 0) + '  (' +
          (total ? (100 * row[1] / total).toFixed(0) : '0') + '%)',
      }));
    });
    svg.appendChild(svgEl('line', {
      x1: labelW, y1: 38, x2: labelW, y2: height - 14,
      stroke: p.axis, 'stroke-width': 1,
    }));
    return svg;
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

  /* ============================================================ map figures */

  /* An equirectangular projection is enough at country scale and keeps the
   * whole map dependency-free. */
  function mapProjection(features, width, height, padding) {
    var pad = padding === undefined ? 18 : padding;
    var lonMin = Infinity, lonMax = -Infinity, latMin = Infinity, latMax = -Infinity;
    function scan(coords) {
      if (typeof coords[0] === 'number') {
        lonMin = Math.min(lonMin, coords[0]); lonMax = Math.max(lonMax, coords[0]);
        latMin = Math.min(latMin, coords[1]); latMax = Math.max(latMax, coords[1]);
        return;
      }
      coords.forEach(scan);
    }
    features.forEach(function (f) {
      if (f.geometry && f.geometry.coordinates) scan(f.geometry.coordinates);
    });
    if (!isFinite(lonMin)) { lonMin = -13.4; lonMax = -10.2; latMin = 6.9; latMax = 10.0; }
    var midLat = (latMin + latMax) / 2;
    var kx = Math.cos(midLat * Math.PI / 180);
    var w = (lonMax - lonMin) * kx, h = latMax - latMin;
    var scale = Math.min((width - 2 * pad) / w, (height - 2 * pad) / h);
    var ox = pad + ((width - 2 * pad) - w * scale) / 2;
    var oy = pad + ((height - 2 * pad) - h * scale) / 2;
    return function (lon, lat) {
      return [ox + (lon - lonMin) * kx * scale, oy + (latMax - lat) * scale];
    };
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

  /* A choropleth over the district or chiefdom boundaries: one hue, light to
   * dark, with the classes named in the legend. */
  function choropleth(spec) {
    var p = palette();
    var width = spec.width || 620, height = spec.height || 560;
    var features = spec.features || [];
    var project = mapProjection(features, width, height - (spec.legend === false ? 10 : 64));
    var svg = svgEl('svg', {
      viewBox: '0 0 ' + width + ' ' + height, width: '100%', xmlns: NS,
      'font-family': FONT, role: 'img', 'aria-label': spec.title || 'map',
    });
    svg.appendChild(svgEl('rect', { width: width, height: height, fill: p.surface }));

    var values = features.map(spec.value).filter(function (v) {
      return typeof v === 'number' && isFinite(v);
    });
    var breaks = spec.breaks || quantileBreaks(values, 5);
    var ramp = p.seq.slice(1, 1 + breaks.length + 1);

    features.forEach(function (feature) {
      var v = spec.value(feature);
      var cls = classify(v, breaks);
      svg.appendChild(svgEl('path', {
        d: geometryPath(feature.geometry, project),
        fill: cls === null ? '#D8D4CB' : ramp[Math.min(cls, ramp.length - 1)],
        stroke: p.surface, 'stroke-width': 0.8,
        'aria-label': (spec.name ? spec.name(feature) : '') +
          (v === null || v === undefined ? '' : ': ' + S.sig(v, 3)),
      }));
    });

    (spec.points || []).forEach(function (point) {
      var pt = project(point.lon, point.lat);
      svg.appendChild(marker(pt[0], pt[1], point.kind || 'circle',
        point.colour || p.secondary, p.surface, point.size || 4.5));
      if (point.label) {
        svg.appendChild(svgEl('text', {
          x: pt[0] + 8, y: pt[1] + 3.5, 'font-size': 10, fill: p.ink,
          stroke: p.surface, 'stroke-width': 2.6, 'paint-order': 'stroke',
          text: point.label,
        }));
      }
    });

    if (spec.title) {
      svg.appendChild(svgEl('text', {
        x: 14, y: 20, 'font-size': 13, 'font-weight': 600, fill: p.ink,
        text: spec.title,
      }));
    }
    if (spec.legend !== false && breaks.length) {
      var ly = height - 34;
      svg.appendChild(svgEl('text', {
        x: 14, y: ly - 8, 'font-size': 10.5, fill: p.muted,
        text: spec.legendTitle || '',
      }));
      ramp.forEach(function (colour, i) {
        var x = 14 + i * 92;
        svg.appendChild(svgEl('rect', {
          x: x, y: ly, width: 16, height: 11, rx: 2, fill: colour,
        }));
        var lo = i === 0 ? null : breaks[i - 1];
        var hi = i < breaks.length ? breaks[i] : null;
        var label = lo === null ? '< ' + S.sig(hi, 3)
          : (hi === null ? '≥ ' + S.sig(lo, 3)
            : S.sig(lo, 3) + '–' + S.sig(hi, 3));
        svg.appendChild(svgEl('text', {
          x: x + 21, y: ly + 9.5, 'font-size': 10, fill: p.inkSoft, text: label,
        }));
      });
    }
    return svg;
  }

  function quantileBreaks(values, n) {
    var xs = values.slice().sort(function (a, b) { return a - b; });
    if (xs.length < n) return xs.slice(1);
    var out = [];
    for (var i = 1; i < n; i++) {
      out.push(xs[Math.floor(i * xs.length / n)]);
    }
    return out.filter(function (v, i, a) { return i === 0 || v !== a[i - 1]; });
  }

  function classify(value, breaks) {
    if (value === null || value === undefined || !isFinite(value)) return null;
    for (var i = 0; i < breaks.length; i++) {
      if (value < breaks[i]) return i;
    }
    return breaks.length;
  }

  /* A site map: boundaries as context, survey points as the data. */
  /* A categorical polygon layer - geology or aquifer productivity - clipped
   * to a window around the site when there is one.
   *
   * The layers carry their own published colours, so the map reads the same
   * way as the source sheet does rather than being recoloured here. Features
   * are selected by bounding-box overlap with the window: a polygon that only
   * touches the edge still belongs on the map, because what surrounds the site
   * is the point of the figure. */
  function thematicMap(spec) {
    var p = palette();
    var width = spec.width || 620, height = spec.height || 520;
    var key = spec.key || 'unit';
    var all = spec.features || [];
    var window_ = spec.window || null;      /* {lat, lon, radiusKm} */

    function bbox(feature) {
      var lonMin = Infinity, lonMax = -Infinity, latMin = Infinity, latMax = -Infinity;
      function scan(coords) {
        if (typeof coords[0] === 'number') {
          lonMin = Math.min(lonMin, coords[0]); lonMax = Math.max(lonMax, coords[0]);
          latMin = Math.min(latMin, coords[1]); latMax = Math.max(latMax, coords[1]);
          return;
        }
        coords.forEach(scan);
      }
      if (feature.geometry && feature.geometry.coordinates) scan(feature.geometry.coordinates);
      return [lonMin, latMin, lonMax, latMax];
    }

    var features = all, clip = null;
    if (window_) {
      var dLat = window_.radiusKm / 110.574;
      var dLon = window_.radiusKm /
        (111.320 * Math.max(Math.cos(window_.lat * Math.PI / 180), 1e-6));
      clip = [window_.lon - dLon, window_.lat - dLat,
        window_.lon + dLon, window_.lat + dLat];
      features = all.filter(function (feature) {
        var b = bbox(feature);
        return isFinite(b[0]) && b[0] <= clip[2] && b[2] >= clip[0] &&
          b[1] <= clip[3] && b[3] >= clip[1];
      });
      if (!features.length) features = all;
    }

    /* the window itself sets the extent, so a 40 km map is a 40 km map even
     * when the polygon covering it runs the length of the country */
    var extent = clip
      ? [{ geometry: { type: 'Polygon', coordinates: [[
        [clip[0], clip[1]], [clip[2], clip[1]], [clip[2], clip[3]], [clip[0], clip[3]],
      ]] } }]
      : features;
    var legendRows = spec.legendItems || [];
    var project = mapProjection(extent, width, height - 24 - legendRows.length * 15, 18);

    var svg = svgEl('svg', {
      viewBox: '0 0 ' + width + ' ' + height, width: '100%', xmlns: NS,
      'font-family': FONT, role: 'img', 'aria-label': spec.title || 'thematic map',
    });
    svg.appendChild(svgEl('rect', { width: width, height: height, fill: p.surface }));

    var clipId = 'gwt-clip-' + Math.abs(width * 7919 + height * 104729 +
      String(spec.title || '').length);
    if (clip) {
      var corner0 = project(clip[0], clip[3]), corner1 = project(clip[2], clip[1]);
      var defs = svgEl('defs');
      defs.appendChild(svgEl('clipPath', { id: clipId }, [svgEl('rect', {
        x: corner0[0], y: corner0[1],
        width: Math.max(1, corner1[0] - corner0[0]),
        height: Math.max(1, corner1[1] - corner0[1]),
      })]));
      svg.appendChild(defs);
    }

    var group = svgEl('g', clip ? { 'clip-path': 'url(#' + clipId + ')' } : {});
    var seen = [];
    features.forEach(function (feature) {
      var props = feature.properties || {};
      var label = props[key] || 'unclassified';
      var colour = props.color || p.neutral;
      group.appendChild(svgEl('path', {
        d: geometryPath(feature.geometry, project),
        fill: colour, 'fill-opacity': 0.82, stroke: p.surface, 'stroke-width': 0.5,
      }, [svgEl('title', { text: String(label) })]));
      if (!seen.some(function (s) { return s.label === label; })) {
        seen.push({ label: String(label), colour: colour });
      }
    });
    svg.appendChild(group);

    (spec.context || []).forEach(function (feature) {
      svg.appendChild(svgEl('path', {
        d: geometryPath(feature.geometry, project), fill: 'none',
        stroke: p.axis, 'stroke-width': 0.8,
      }));
    });

    (spec.points || []).forEach(function (point) {
      var pt = project(point.lon, point.lat);
      svg.appendChild(marker(pt[0], pt[1], point.kind || 'diamond',
        point.colour || p.secondary, p.surface, point.size || 7));
      if (point.label) {
        svg.appendChild(svgEl('text', {
          x: pt[0] + 10, y: pt[1] + 3.5, 'font-size': 10.5, fill: p.ink,
          stroke: p.surface, 'stroke-width': 3, 'paint-order': 'stroke',
          text: point.label,
        }));
      }
    });

    if (spec.title) {
      svg.appendChild(svgEl('text', {
        x: 14, y: 20, 'font-size': 13, 'font-weight': 600, fill: p.ink,
        text: spec.title,
      }));
    }
    seen.slice(0, 8).forEach(function (item, i) {
      var y = height - 12 - (Math.min(seen.length, 8) - 1 - i) * 15;
      svg.appendChild(svgEl('rect', {
        x: 16, y: y - 8, width: 11, height: 11, rx: 2,
        fill: item.colour, stroke: p.axis, 'stroke-width': 0.5,
      }));
      svg.appendChild(svgEl('text', {
        x: 33, y: y, 'font-size': 10.5, fill: p.inkSoft,
        text: item.label.length > 62 ? item.label.slice(0, 60) + '…' : item.label,
      }));
    });
    return svg;
  }

  function siteMap(spec) {
    var p = palette();
    var width = spec.width || 620, height = spec.height || 520;
    var context = spec.context || [];
    var project = mapProjection(context.length ? context : (spec.points || []).map(function (pt) {
      return { geometry: { type: 'Polygon', coordinates: [[[pt.lon, pt.lat]]] } };
    }), width, height);
    var svg = svgEl('svg', {
      viewBox: '0 0 ' + width + ' ' + height, width: '100%', xmlns: NS,
      'font-family': FONT, role: 'img', 'aria-label': spec.title || 'site map',
    });
    svg.appendChild(svgEl('rect', { width: width, height: height, fill: p.surface }));
    context.forEach(function (feature) {
      svg.appendChild(svgEl('path', {
        d: geometryPath(feature.geometry, project),
        fill: spec.contextFill ? spec.contextFill(feature) : '#EDEAE3',
        stroke: p.axis, 'stroke-width': 0.7,
      }));
    });
    (spec.points || []).forEach(function (point) {
      var pt = project(point.lon, point.lat);
      svg.appendChild(marker(pt[0], pt[1], point.kind || 'circle',
        point.colour || p.accent, p.surface, point.size || 5.5));
      if (point.label) {
        svg.appendChild(svgEl('text', {
          x: pt[0] + 9, y: pt[1] + 3.5, 'font-size': 10.5, fill: p.ink,
          stroke: p.surface, 'stroke-width': 2.8, 'paint-order': 'stroke',
          text: point.label,
        }));
      }
    });
    if (spec.title) {
      svg.appendChild(svgEl('text', {
        x: 14, y: 20, 'font-size': 13, 'font-weight': 600, fill: p.ink, text: spec.title,
      }));
    }
    if (spec.legendItems && spec.legendItems.length) {
      spec.legendItems.forEach(function (item, i) {
        var y = height - 14 - (spec.legendItems.length - 1 - i) * 15;
        svg.appendChild(marker(22, y - 3.5, item.kind || 'circle', item.colour,
          p.surface, 4.5));
        svg.appendChild(svgEl('text', {
          x: 34, y: y, 'font-size': 10.5, fill: p.inkSoft, text: item.label,
        }));
      });
    }
    return svg;
  }

  /* ============================================================ export */

  /* Rasterise an SVG to a PNG data URL for embedding in the .docx reports.
   * Elements marked data-export="skip" (the hover layer) are dropped first. */
  function toPng(svg, options) {
    var opts = options || {};
    var scale = opts.scale || 2;
    var clone = svg.cloneNode(true);
    Array.prototype.slice.call(clone.querySelectorAll('[data-export="skip"]'))
      .forEach(function (node) { node.parentNode.removeChild(node); });
    var viewBox = (clone.getAttribute('viewBox') || '0 0 720 420').split(/\s+/).map(Number);
    var w = viewBox[2], h = viewBox[3];
    clone.setAttribute('width', w);
    clone.setAttribute('height', h);
    clone.setAttribute('xmlns', NS);
    var source = new XMLSerializer().serializeToString(clone);
    var url = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(source);

    return new Promise(function (resolve, reject) {
      var img = new Image();
      img.onload = function () {
        var canvas = document.createElement('canvas');
        canvas.width = Math.round(w * scale);
        canvas.height = Math.round(h * scale);
        var ctx = canvas.getContext('2d');
        ctx.fillStyle = opts.background || '#FFFFFF';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
        resolve({
          dataUrl: canvas.toDataURL('image/png'),
          width: canvas.width, height: canvas.height,
          widthPx: w, heightPx: h,
        });
      };
      img.onerror = function () { reject(new Error('Could not rasterise the figure.')); };
      img.src = url;
    });
  }

  function download(svg, filename) {
    var clone = svg.cloneNode(true);
    Array.prototype.slice.call(clone.querySelectorAll('[data-export="skip"]'))
      .forEach(function (node) { node.parentNode.removeChild(node); });
    clone.setAttribute('xmlns', NS);
    S.download(filename, new XMLSerializer().serializeToString(clone),
      'image/svg+xml;charset=utf-8');
  }

  /* A figure block: the SVG, a numbered caption, and the buttons that export
   * it or show the numbers as a table. */
  function figure(svg, caption, options) {
    var opts = options || {};
    if (!svg) return null;
    var actions = el('div.figure-actions', [
      opts.table ? S.button('Table', function () {
        S.modal(caption || 'Figure data', opts.table());
      }, { variant: 'quiet' }) : null,
      S.button('PNG', function () {
        toPng(svg, { scale: 2 }).then(function (png) {
          fetch(png.dataUrl).then(function (r) { return r.blob(); })
            .then(function (blob) {
              S.download((opts.filename || S.slug(caption || 'figure')) + '.png', blob);
            });
        });
      }, { variant: 'quiet' }),
      S.button('SVG', function () {
        download(svg, (opts.filename || S.slug(caption || 'figure')) + '.svg');
      }, { variant: 'quiet' }),
    ]);
    return el('figure.figure', [
      svg,
      caption ? el('figcaption', [
        opts.number ? el('span.fig-no', 'Figure ' + opts.number) : null,
        el('span', caption),
        actions,
      ]) : el('figcaption', actions),
    ]);
  }

  GWT.charts = {
    palette: palette, frame: frame, marker: marker, legend: legend,
    polyline: polyline, padDomain: padDomain, freeCorner: freeCorner, linTicks: linTicks, logTicks: logTicks,
    vesCurve: vesCurve, layeredModel: layeredModel,
    testOverview: testOverview, cooperJacob: cooperJacob,
    recovery: recoveryPlot, stepTest: stepTestPlot,
    piper: piper, stiff: stiff, boreholeDesign: boreholeDesign,
    lithologyColour: lithologyColour,
    depthSpine: depthSpine, guidelineSpine: guidelineSpine,
    costBreakdown: costBreakdown, programmeGantt: programmeGantt,
    choropleth: choropleth, siteMap: siteMap, thematicMap: thematicMap,
    mapProjection: mapProjection,
    geometryPath: geometryPath, quantileBreaks: quantileBreaks,
    toPng: toPng, downloadSvg: download, figure: figure,
  };
}(typeof window !== 'undefined' ? window : globalThis));

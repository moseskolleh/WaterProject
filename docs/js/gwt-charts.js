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

  var CAT_FALLBACK = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100',
    '#e87ba4', '#008300', '#4a3aa7', '#e34948'];
  var SEQ_FALLBACK = ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5',
    '#256abf', '#184f95', '#0d366b'];

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
      /* The fallbacks are the stylesheet's own values, one per slot. A single
       * fallback for the whole family collapsed every series to one colour
       * anywhere the tokens could not be read - which is exactly where a
       * figure is rasterised for a report. */
      cat: CAT_FALLBACK.map(function (fallback, i) {
        return token('cat-' + (i + 1), fallback);
      }),
      seq: SEQ_FALLBACK.map(function (fallback, i) {
        return token('seq-' + (i + 1), fallback);
      }),
      good: token('status-good', '#0ca30c'),
      warning: token('status-warning', '#fab219'),
      serious: token('status-serious', '#ec835a'),
      critical: token('status-critical', '#d03b3b'),
    };
  }

  /* ------------------------------------------------------- text geometry
   *
   * There is no way to measure text before it is in the document, and the
   * figures are built detached so they can be rasterised without ever being
   * shown. These two functions are the estimate everything else lays out
   * against: they are deliberately a little generous, because a label with a
   * few spare pixels reads fine and a label three pixels too wide is clipped.
   */
  function textWidth(text, size) {
    var s = String(text === null || text === undefined ? '' : text);
    var w = 0;
    for (var i = 0; i < s.length; i++) {
      var c = s.charCodeAt(i);
      /* i/l/j/t/f/r and punctuation are narrow; capitals and m/w are wide */
      if ('iljt.,:;\'`|!'.indexOf(s[i]) >= 0) w += 0.30;
      else if ('fr()[]{}/\\ '.indexOf(s[i]) >= 0) w += 0.38;
      else if ('mwMW@'.indexOf(s[i]) >= 0) w += 0.90;
      else if (c >= 65 && c <= 90) w += 0.68;
      else w += 0.545;
    }
    return w * (size || 10);
  }

  /* Break `text` into lines no wider than `maxWidth`. Words longer than the
   * line are broken rather than allowed to run past the edge. */
  function wrapText(text, maxWidth, size) {
    var words = String(text === null || text === undefined ? '' : text)
      .split(/\s+/).filter(Boolean);
    var lines = [], line = '';
    function flush() { if (line) { lines.push(line); line = ''; } }
    words.forEach(function (word) {
      var candidate = line ? line + ' ' + word : word;
      if (textWidth(candidate, size) <= maxWidth) { line = candidate; return; }
      flush();
      while (textWidth(word, size) > maxWidth && word.length > 1) {
        var cut = word.length;
        while (cut > 1 && textWidth(word.slice(0, cut) + '-', size) > maxWidth) cut -= 1;
        lines.push(word.slice(0, cut) + '-');
        word = word.slice(cut);
      }
      line = word;
    });
    flush();
    return lines.length ? lines : [''];
  }

  /* One line, shortened with an ellipsis only when it genuinely will not fit.
   * Nothing in these figures truncates mid-word without saying so. */
  function ellipsise(text, maxWidth, size) {
    var s = String(text === null || text === undefined ? '' : text);
    if (textWidth(s, size) <= maxWidth) return s;
    var cut = s.length;
    while (cut > 1 && textWidth(s.slice(0, cut) + '…', size) > maxWidth) cut -= 1;
    return s.slice(0, cut).replace(/[\s,;:.-]+$/, '') + '…';
  }

  /* Place labels against their anchors without letting any two collide, and
   * without letting any escape the drawing. Labels are sorted by anchor,
   * pushed down until they clear the one above, then pulled back up from the
   * bottom so the last one stays inside `yMax`. Returns {y, entry} pairs in
   * anchor order. This is the same algorithm the matplotlib drawing uses, so
   * the browser figure and the report figure lay their callouts out alike. */
  function stackLabels(entries, minGap, yMin, yMax) {
    var placed = entries.slice().sort(function (a, b) { return a.anchor - b.anchor; })
      .map(function (entry) { return { y: entry.anchor, entry: entry }; });
    var level = yMin;
    placed.forEach(function (item) {
      item.y = Math.max(item.y, level);
      level = item.y + minGap;
    });
    var limit = yMax;
    for (var i = placed.length - 1; i >= 0; i--) {
      if (placed[i].y > limit) placed[i].y = limit;
      limit = placed[i].y - minGap;
    }
    return placed;
  }

  /* Black or white, whichever stays readable on `hex`. Used wherever a label
   * is written straight onto a fill whose colour comes from the data. */
  function readableInk(hex) {
    var m = /^#?([0-9a-f]{6})$/i.exec(String(hex || '').trim());
    if (!m) return '#FFFFFF';
    var n = parseInt(m[1], 16);
    function lin(v) {
      var c = v / 255;
      return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    }
    var L = 0.2126 * lin((n >> 16) & 255) + 0.7152 * lin((n >> 8) & 255) +
      0.0722 * lin(n & 255);
    return (L + 0.05) / 0.05 > 1.05 / (L + 0.05) ? '#12191A' : '#FFFFFF';
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
      /* a tick label centred on the last tick hangs off the right edge of the
       * viewBox; the outermost ones are anchored inwards instead */
      var label = t.label === undefined ? tickLabel(t) : t.label;
      var half = textWidth(label, 11) / 2;
      var anchor = 'middle';
      if (x + half > width - 3) anchor = 'end';
      else if (x - half < 3) anchor = 'start';
      grid.appendChild(svgEl('text', {
        x: anchor === 'end' ? Math.min(x + half, width - 3)
          : (anchor === 'start' ? Math.max(x - half, 3) : x),
        y: margin.top + plotH + 17, 'text-anchor': anchor,
        'font-size': 11, fill: p.muted, text: label,
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
      widest = Math.max(widest, textWidth(entry.label, 11));
    });
    box.setAttribute('width', 30 + widest + pad);
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
      xLabel: 'Resistivity (\u03A9\u00B7m)', yLabel: 'Depth (m)',
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
    /* The gap between the two triangles is not cosmetic: it sets where the
     * diamond sits, and C.piperPoints is given the same figure so the three
     * plots stay one construction. It has to be wide enough for the two
     * labels that meet in it - Na+K and HCO3 - to stand side by side, or
     * they overprint each other. */
    var size = opts.size || 200, gap = 64;
    var titleH = opts.title === null ? 10 : 32;
    var p = palette();

    /* the construction is measured, not guessed: the figure is exactly as
     * tall as the diamond's apex plus the labels above and below it */
    var stackPx = SQ3 / 2 * gap + SQ3 * size;
    var ox = 40;
    var oy = titleH + 16 + stackPx;
    var width = opts.width || (2 * size + gap + 80);
    var height = opts.height || (oy + 34);

    var svg = svgEl('svg', {
      viewBox: '0 0 ' + width + ' ' + height, width: '100%', xmlns: NS,
      'font-family': FONT, role: 'img', 'aria-label': 'Piper diagram',
    });
    svg.appendChild(svgEl('rect', { width: width, height: height, fill: p.surface }));
    if (opts.title !== null) {
      svg.appendChild(svgEl('text', {
        x: 16, y: 20, 'font-size': 13, 'font-weight': 620, fill: p.ink,
        text: opts.title || 'Piper diagram',
      }));
    }
    ox = (width - (2 * size + gap)) / 2;
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
      g.appendChild(svgEl('text', { x: x0, y: y0 + 16, 'text-anchor': 'middle',
        'font-size': 11, fill: p.inkSoft, text: labels[0] }));
      g.appendChild(svgEl('text', { x: x0 + size, y: y0 + 16, 'text-anchor': 'middle',
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
    /* The diamond is an affine image of the unit square: from its bottom
     * corner, u runs along the Na+K axis and v along the SO4+Cl axis. Both
     * grid families fall straight out of that, which is also how a point is
     * read back off the figure. */
    function diamondPoint(u, v) {
      return place({ x: xMid + 0.5 * u - 0.5 * v, y: yBot + SQ3 / 2 * (u + v) });
    }
    var dgrid = svgEl('g', { 'aria-hidden': 'true' });
    [0.2, 0.4, 0.6, 0.8].forEach(function (frac) {
      [[[frac, 0], [frac, 1]], [[0, frac], [1, frac]]].forEach(function (pair) {
        var a = diamondPoint(pair[0][0], pair[0][1]);
        var b = diamondPoint(pair[1][0], pair[1][1]);
        dgrid.appendChild(polyline([[a.x, a.y], [b.x, b.y]],
          { stroke: p.grid, 'stroke-width': 0.8 }));
      });
    });
    svg.appendChild(dgrid);
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
      /* clear of the line above the diamond, which is centred and wide */
      var lx = 24, ly = titleH + 40;
      var widest = entries.reduce(function (m, e) {
        return Math.max(m, textWidth(e.label, 11));
      }, 0);
      lg.appendChild(svgEl('rect', {
        x: lx - 10, y: ly - 15, rx: 4, fill: p.surface, stroke: p.grid,
        'stroke-width': 1, 'fill-opacity': 0.94,
        width: widest + 40, height: entries.length * 17 + 8,
      }));
      entries.forEach(function (e, i) {
        lg.appendChild(marker(lx, ly + i * 17 - 4, e.kind, e.colour, p.surface, 4.5));
        lg.appendChild(svgEl('text', { x: lx + 14, y: ly + i * 17,
          'font-size': 11, fill: p.inkSoft, text: e.label }));
      });
      svg.appendChild(lg);
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
  /* The colour stands for a class of material, not for one driller's wording,
   * so the legend names the class. Order matters: the first pattern that
   * matches wins, and a fracture zone is called a fracture zone whatever rock
   * it is in. */
  var LITHOLOGY_COLOURS = [
    [/fracture|fissure/i, '#6D8FA8', 'Fracture zone'],
    [/laterite|duricrust|topsoil/i, '#B5651D', 'Laterite and topsoil'],
    [/clay|saprolite/i, '#9E8B5F', 'Clay and saprolite'],
    [/sand|gravel/i, '#C8B57C', 'Sand and gravel'],
    [/weather|regolith/i, '#A98F63', 'Weathered rock'],
    [/fresh|granite|basement|bedrock|gneiss|schist/i, '#7E7F84', 'Fresh basement'],
  ];
  var LITHOLOGY_OTHER = ['#B0A99C', 'Other material'];

  function lithologyClass(description) {
    for (var i = 0; i < LITHOLOGY_COLOURS.length; i++) {
      if (LITHOLOGY_COLOURS[i][0].test(description || '')) {
        return { colour: LITHOLOGY_COLOURS[i][1], label: LITHOLOGY_COLOURS[i][2] };
      }
    }
    return { colour: LITHOLOGY_OTHER[0], label: LITHOLOGY_OTHER[1] };
  }

  function lithologyColour(description) {
    return lithologyClass(description).colour;
  }

  /* A well-completion section, drawn the way a driller draws one.
   *
   * Depth is to scale; width is not, because a 5" casing in a 6.5" hole at
   * 70 m would be a hairline. What the width does carry is the order of the
   * materials across the hole - formation, annulus fill, casing wall, the
   * water standing inside the casing - so the section reads as a section and
   * not as a bar chart.
   *
   * Everything that has to be said in words is said in one of three gutters:
   * the formation column on the left, the water gutter between it and the
   * hole, and the construction callouts on the right. Nothing is written
   * across the drawing, and no callout is allowed to land on another: they
   * are placed by stackLabels() against a leader line back to the thing they
   * name.
   */
  var patternSeq = 0;

  function fillPatterns(defs, kinds) {
    /* Returns {kind: 'url(#id)'}. Patterns rather than flat fills so the
     * section still reads when it is printed in monochrome. */
    var out = {};
    patternSeq += 1;
    Object.keys(kinds).forEach(function (kind) {
      var spec = kinds[kind];
      var id = 'gwt-fill-' + patternSeq + '-' + kind;
      var pattern = svgEl('pattern', {
        id: id, width: spec.size, height: spec.size,
        patternUnits: 'userSpaceOnUse',
      });
      pattern.appendChild(svgEl('rect', {
        width: spec.size, height: spec.size, fill: spec.background,
      }));
      spec.marks.forEach(function (mark) { pattern.appendChild(mark); });
      defs.appendChild(pattern);
      out[kind] = 'url(#' + id + ')';
    });
    return out;
  }

  function boreholeDesign(design, log, options) {
    var opts = options || {};
    var p = palette();
    var width = opts.width || 800;

    /* 5.0 -> 5, 6.5 -> 6.5: a diameter is quoted the way it is stamped */
    function trim(v) {
      return typeof v === 'number' ? String(Math.round(v * 100) / 100) : String(v);
    }

    var depth = design.total_depth_m || 1;
    var stickup = design.stickup_m || 0;
    var swl = (design.static_water_level_m === null ||
      design.static_water_level_m === undefined) ? null : design.static_water_level_m;

    /* ------------------------------------------------------------ colours */
    var COLOUR = {
      gravel: '#D9C89A', gravelMark: '#9C8A55',
      backfill: '#CFC9BB', backfillMark: '#938C7C',
      seal: '#9BA3A8', sealMark: '#6E777D',
      casing: '#EDEBE4', casingEdge: '#5C6360',
      screen: p.accent, sump: '#7E8B92',
      water: '#CBE3F5', waterEdge: '#7FB0DA',
      concrete: '#BEBBB2', ground: '#8A8577',
      rising: '#B7BDBB', pump: '#4D5457',
    };

    /* --------------------------------------------------------- the legend
     * built first, because how many rows it needs decides how tall the
     * drawing has to be for the section itself to keep its room */
    var litho = (log && log.intervals) || [];
    var lithoKeys = [];
    litho.forEach(function (interval) {
      var klass = lithologyClass(interval.description);
      if (!lithoKeys.some(function (k) { return k.label === klass.label; })) {
        lithoKeys.push({ label: klass.label, colour: klass.colour });
      }
    });
    /* The construction materials come first because they are what the reader
     * is being asked to check; the formation classes follow. Each interval is
     * already named in the column beside it, so the legend explains what a
     * colour means rather than repeating twelve descriptions. */
    var legendItems = [
      { label: 'Gravel pack', colour: COLOUR.gravel, fill: 'gravel' },
      { label: 'Annular backfill', colour: COLOUR.backfill, fill: 'backfill' },
      { label: 'Cement sanitary seal', colour: COLOUR.seal, fill: 'seal' },
      { label: 'Plain casing', colour: COLOUR.casing },
      { label: 'Screen', colour: COLOUR.screen },
      { label: 'Sump', colour: COLOUR.sump },
    ];
    if (swl !== null) legendItems.push({ label: 'Water in the casing', colour: COLOUR.water });
    legendItems = legendItems.concat(lithoKeys);

    var legendCols = 2;
    var legendColW = (width - 32) / legendCols;
    var legendRowH = 16;
    var legendRows = Math.ceil(legendItems.length / legendCols);
    var legendH = legendRows * legendRowH + 22;

    /* ------------------------------------------------------------- layout */
    var titleY = 22;
    var headerY = 40;
    var groundY = opts.groundY || 96;           /* y of ground level */
    var depthPx = opts.depthPx || 560;          /* pixels for the whole hole */
    var height = opts.height || (groundY + depthPx + 46 + legendH);

    var axisX = 74;                              /* the depth ruler */
    var lithX = 92, lithW = 132;                 /* formation column */
    var holeCx = Math.round(width * 0.545), holeHalf = 46;
    var casHalf = 21, wall = 7;
    var boreX0 = holeCx - holeHalf, boreX1 = holeCx + holeHalf;
    var labelX = boreX1 + 78;                    /* construction callouts */
    var labelMaxW = width - 14 - labelX;

    var depthMax = depth * 1.015;
    function fy(d) { return groundY + (d / depthMax) * depthPx; }
    var bottomY = fy(depth);
    var stickPx = Math.max(16, Math.min(34, fy(stickup) - groundY || 20));

    var svg = svgEl('svg', {
      viewBox: '0 0 ' + width + ' ' + height, width: '100%', xmlns: NS,
      'font-family': FONT, role: 'img',
      'aria-label': 'Borehole construction design, drawn to scale with depth',
    });
    svg.appendChild(svgEl('rect', { width: width, height: height, fill: p.surface }));

    var defs = svgEl('defs');
    svg.appendChild(defs);
    var fills = fillPatterns(defs, {
      gravel: {
        size: 9, background: COLOUR.gravel,
        marks: [
          svgEl('circle', { cx: 2.6, cy: 2.6, r: 1.25, fill: COLOUR.gravelMark }),
          svgEl('circle', { cx: 6.8, cy: 6.4, r: 1.05, fill: COLOUR.gravelMark }),
          svgEl('circle', { cx: 7.2, cy: 1.8, r: 0.8, fill: COLOUR.gravelMark }),
        ],
      },
      backfill: {
        size: 7, background: COLOUR.backfill,
        marks: [
          svgEl('circle', { cx: 1.8, cy: 1.8, r: 0.6, fill: COLOUR.backfillMark }),
          svgEl('circle', { cx: 5.2, cy: 4.8, r: 0.6, fill: COLOUR.backfillMark }),
        ],
      },
      seal: {
        size: 7, background: COLOUR.seal,
        marks: [
          svgEl('path', {
            d: 'M-2 2L2 -2M0 8L8 0M6 10L10 6', stroke: COLOUR.sealMark,
            'stroke-width': 1.1,
          }),
        ],
      },
      concrete: {
        size: 8, background: COLOUR.concrete,
        marks: [
          svgEl('path', {
            d: 'M-2 6L6 -2M2 10L10 2', stroke: '#8E8B83', 'stroke-width': 0.9,
          }),
        ],
      },
    });

    svg.appendChild(svgEl('text', {
      x: 16, y: titleY, 'font-size': 13.5, 'font-weight': 640, fill: p.ink,
      text: opts.title || 'Borehole construction design',
    }));
    if (opts.subtitle) {
      svg.appendChild(svgEl('text', {
        x: 16, y: titleY + 17, 'font-size': 10.5, fill: p.muted,
        text: ellipsise(opts.subtitle, width - 32, 10.5),
      }));
    }

    /* ------------------------------------------------------ column headers */
    function header(x, anchor, text) {
      svg.appendChild(svgEl('text', {
        x: x, y: headerY + 26, 'text-anchor': anchor, 'font-size': 10,
        'font-weight': 620, fill: p.inkSoft, 'letter-spacing': '0.04em',
        text: text,
      }));
    }
    header(axisX, 'end', 'DEPTH (m)');
    header(lithX + lithW / 2, 'middle', 'FORMATION');
    header(holeCx, 'middle', 'CONSTRUCTION');

    /* -------------------------------------------------------- depth ruler */
    svg.appendChild(svgEl('line', {
      x1: axisX, y1: groundY, x2: axisX, y2: bottomY,
      stroke: p.axis, 'stroke-width': 1,
    }));
    var step = depth > 120 ? 20 : depth > 60 ? 10 : depth > 24 ? 5 : 2;
    for (var d = 0; d <= depth + 1e-9; d += step) {
      var ty = fy(d);
      svg.appendChild(svgEl('line', {
        x1: axisX - 5, y1: ty, x2: axisX, y2: ty, stroke: p.axis, 'stroke-width': 1,
      }));
      svg.appendChild(svgEl('text', {
        x: axisX - 9, y: ty + 3.6, 'text-anchor': 'end', 'font-size': 10,
        fill: p.muted, text: String(Math.round(d * 10) / 10),
      }));
    }
    if (Math.abs(depth % step) > 1e-6) {
      svg.appendChild(svgEl('text', {
        x: axisX - 9, y: bottomY + 3.6, 'text-anchor': 'end', 'font-size': 10,
        'font-weight': 620, fill: p.inkSoft, text: String(Math.round(depth * 10) / 10),
      }));
    }

    /* --------------------------------------------------- formation column */
    if (litho.length) {
      litho.forEach(function (interval) {
        var colour = lithologyColour(interval.description);
        var y0 = fy(Math.max(0, interval.top_m));
        var y1 = fy(Math.min(interval.bottom_m, depth));
        if (y1 <= y0) return;
        svg.appendChild(svgEl('rect', {
          x: lithX, y: y0, width: lithW, height: y1 - y0,
          fill: colour, stroke: '#FFFFFF', 'stroke-width': 0.8,
        }, [svgEl('title', {
          text: interval.top_m + '–' + interval.bottom_m + ' m: ' +
            (interval.description || ''),
        })]));
        var lines = wrapText(interval.description || '', lithW - 12, 8.5);
        var fits = Math.floor((y1 - y0 - 4) / 10);
        if (fits >= 1) {
          if (lines.length > fits) {
            lines = lines.slice(0, fits);
            lines[fits - 1] = ellipsise(lines[fits - 1] + ' …', lithW - 12, 8.5);
          }
          var ink = readableInk(colour);
          var first = (y0 + y1) / 2 - (lines.length - 1) * 5 + 3;
          lines.forEach(function (line, i) {
            svg.appendChild(svgEl('text', {
              x: lithX + lithW / 2, y: first + i * 10, 'text-anchor': 'middle',
              'font-size': 8.5, fill: ink, text: line,
            }));
          });
        }
      });
    } else {
      svg.appendChild(svgEl('rect', {
        x: lithX, y: groundY, width: lithW, height: bottomY - groundY,
        fill: '#E4E1D9', stroke: p.axis, 'stroke-width': 1,
      }));
      svg.appendChild(svgEl('text', {
        x: lithX + lithW / 2, y: (groundY + bottomY) / 2, 'text-anchor': 'middle',
        'font-size': 10, fill: p.muted, text: 'no drilling log',
      }));
    }
    svg.appendChild(svgEl('rect', {
      x: lithX, y: groundY, width: lithW, height: bottomY - groundY,
      fill: 'none', stroke: p.axis, 'stroke-width': 0.9,
    }));

    /* ------------------------------------------------------------ annulus */
    function annulus(range, fill) {
      if (!range) return;
      var y0 = fy(Math.max(0, range[0])), y1 = fy(Math.min(range[1], depth));
      if (y1 <= y0) return;
      [[boreX0, holeCx - casHalf], [holeCx + casHalf, boreX1]].forEach(function (span) {
        svg.appendChild(svgEl('rect', {
          x: span[0], y: y0, width: span[1] - span[0], height: y1 - y0,
          fill: fill, stroke: 'none',
        }));
      });
    }
    annulus(design.gravel_pack, fills.gravel);
    annulus(design.backfill, fills.backfill);
    annulus(design.sanitary_seal, fills.seal);

    /* ----------------------------------------------- water in the casing */
    var innerX = holeCx - casHalf + wall;
    var innerW = 2 * (casHalf - wall);
    if (swl !== null && swl < depth) {
      svg.appendChild(svgEl('rect', {
        x: innerX, y: fy(swl), width: innerW, height: bottomY - fy(swl),
        fill: COLOUR.water,
      }));
    }

    /* --------------------------------------------------------- hole walls */
    svg.appendChild(svgEl('path', {
      d: 'M' + boreX0 + ' ' + groundY + 'V' + bottomY + 'H' + boreX1 + 'V' + groundY,
      fill: 'none', stroke: p.inkSoft, 'stroke-width': 1.5,
    }));

    /* ------------------------------------------------------ casing string */
    var segments = (design.segments || []).slice().sort(function (a, b) {
      return a.top_m - b.top_m;
    });
    segments.forEach(function (seg) {
      var y0 = fy(Math.max(0, seg.top_m)), y1 = fy(Math.min(seg.bottom_m, depth));
      if (y1 <= y0) return;
      var fill = seg.kind === 'screen' ? COLOUR.screen
        : seg.kind === 'sump' ? COLOUR.sump : COLOUR.casing;
      [holeCx - casHalf, holeCx + casHalf - wall].forEach(function (x) {
        svg.appendChild(svgEl('rect', {
          x: x, y: y0, width: wall, height: y1 - y0,
          fill: fill, stroke: COLOUR.casingEdge, 'stroke-width': 0.8,
        }));
        if (seg.kind === 'screen') {
          for (var sy = y0 + 3; sy < y1 - 1.5; sy += 4.5) {
            svg.appendChild(svgEl('line', {
              x1: x + 0.9, y1: sy, x2: x + wall - 0.9, y2: sy,
              stroke: '#FFFFFF', 'stroke-width': 1.4,
            }));
          }
        }
      });
      /* water entering through the screen: the point of the whole drawing */
      if (seg.kind === 'screen' && y1 - y0 > 16) {
        var arrows = Math.max(1, Math.min(4, Math.floor((y1 - y0) / 26)));
        for (var a = 0; a < arrows; a++) {
          var ay = y0 + (y1 - y0) * (a + 0.5) / arrows;
          [-1, 1].forEach(function (side) {
            var tipX = holeCx + side * (casHalf - wall - 1);
            var tailX = holeCx + side * (holeHalf - 5);
            svg.appendChild(svgEl('path', {
              d: 'M' + tailX + ' ' + ay + 'L' + tipX + ' ' + ay,
              stroke: COLOUR.waterEdge, 'stroke-width': 1.2,
            }));
            svg.appendChild(svgEl('path', {
              d: 'M' + tipX + ' ' + ay + 'l' + (side * 4.5) + ' -2.6v5.2z',
              fill: COLOUR.waterEdge,
            }));
          });
        }
      }
    });

    /* bottom cap, drawn across the casing so the string is visibly closed */
    svg.appendChild(svgEl('rect', {
      x: holeCx - casHalf, y: bottomY - 5, width: 2 * casHalf, height: 5,
      fill: COLOUR.pump, stroke: COLOUR.casingEdge, 'stroke-width': 0.8,
    }));

    /* ------------------------------------------- rising main and the pump */
    var intake = (design.pump_intake_m === null || design.pump_intake_m === undefined)
      ? null : design.pump_intake_m;
    if (intake !== null && intake < depth) {
      var iy = fy(intake);
      svg.appendChild(svgEl('rect', {
        x: holeCx - 3.5, y: groundY - stickPx + 4, width: 7, height: iy - groundY + stickPx - 4,
        fill: COLOUR.rising, stroke: COLOUR.casingEdge, 'stroke-width': 0.7,
      }));
      svg.appendChild(svgEl('rect', {
        x: holeCx - 8, y: iy - 6, width: 16, height: 26, rx: 3,
        fill: COLOUR.pump, stroke: '#FFFFFF', 'stroke-width': 1,
      }));
    }

    /* ---------------------------------------------------------- headworks */
    /* ground line, with the soil side of it shaded so up is unambiguous */
    svg.appendChild(svgEl('line', {
      x1: axisX, y1: groundY, x2: boreX1 + 46, y2: groundY,
      stroke: COLOUR.ground, 'stroke-width': 1.6,
    }));

    for (var gx = axisX; gx < boreX1 + 60; gx += 9) {
      if (gx > lithX - 4 && gx < lithX + lithW + 4) continue;
      if (gx > boreX0 - 42 && gx < boreX1 + 42) continue;
      svg.appendChild(svgEl('line', {
        x1: gx, y1: groundY, x2: gx - 5, y2: groundY - 5,
        stroke: COLOUR.ground, 'stroke-width': 0.8,
      }));
    }
    /* apron slab and plinth */
    svg.appendChild(svgEl('rect', {
      x: boreX0 - 38, y: groundY - 7, width: 2 * (holeHalf + 38), height: 9,
      fill: fills.concrete, stroke: COLOUR.casingEdge, 'stroke-width': 0.8,
    }));
    svg.appendChild(svgEl('rect', {
      x: holeCx - casHalf - 13, y: groundY - stickPx + 8, width: 2 * casHalf + 26,
      height: stickPx - 1, fill: fills.concrete,
      stroke: COLOUR.casingEdge, 'stroke-width': 0.8,
    }));
    /* the casing above ground, and its cap */
    [holeCx - casHalf, holeCx + casHalf - wall].forEach(function (x) {
      svg.appendChild(svgEl('rect', {
        x: x, y: groundY - stickPx, width: wall, height: stickPx,
        fill: COLOUR.casing, stroke: COLOUR.casingEdge, 'stroke-width': 0.8,
      }));
    });
    svg.appendChild(svgEl('rect', {
      x: holeCx - casHalf - 4, y: groundY - stickPx - 6, width: 2 * casHalf + 8,
      height: 6, rx: 1.5, fill: COLOUR.casingEdge,
    }));

    /* ------------------------------------ water gutter: SWL and the strikes */
    var gutterRight = boreX0 - 12;
    var gutterLeft = lithX + lithW + 6;
    var gutterW = gutterRight - gutterLeft;
    var gutterEntries = [];
    if (swl !== null) {
      gutterEntries.push({
        anchor: fy(swl), colour: p.cat[0],
        text: 'SWL ' + S.fmt(swl, 2) + ' m', swl: true,
      });
    }
    (design.water_strikes_m || []).forEach(function (strike) {
      gutterEntries.push({
        anchor: fy(strike), colour: p.secondary,
        text: 'strike ' + S.fmt(strike, strike % 1 ? 1 : 0) + ' m',
      });
    });
    stackLabels(gutterEntries, 14, groundY + 7, bottomY - 2)
      .forEach(function (item) {
        var e = item.entry;
        if (e.swl) {
          svg.appendChild(svgEl('line', {
            x1: gutterRight - 4, y1: e.anchor, x2: boreX1 + 6, y2: e.anchor,
            stroke: e.colour, 'stroke-width': 1.5, 'stroke-dasharray': '6 3',
          }));
          svg.appendChild(marker(holeCx, e.anchor, 'triangle', e.colour,
            p.surface, 4.5));
        } else {
          svg.appendChild(svgEl('path', {
            d: 'M' + boreX0 + ' ' + e.anchor + 'l-8 -4v8z', fill: e.colour,
          }));
          svg.appendChild(svgEl('line', {
            x1: gutterRight - 4, y1: item.y, x2: boreX0 - 9, y2: e.anchor,
            stroke: e.colour, 'stroke-width': 0.8,
          }));
        }
        svg.appendChild(svgEl('text', {
          x: gutterRight - 7, y: item.y + 3.4, 'text-anchor': 'end',
          'font-size': 9.5, fill: e.colour,
          text: ellipsise(e.text, gutterW - 12, 9.5),
        }));
      });

    /* --------------------------------------------- construction callouts */
    var callouts = [];
    function callout(fromM, toM, text) {
      if (fromM === null || fromM === undefined) return;
      var a = Math.max(0, fromM), b = Math.min(toM === undefined ? fromM : toM, depth);
      if (b < a) return;
      callouts.push({ anchor: fy((a + b) / 2), text: text });
    }
    callout(-stickup, 0, 'Stick-up ' + S.fmt(stickup, 1) + ' m, ' +
      trim(design.casing_diameter_in) + '" ' + (design.casing_material || 'uPVC') +
      ' in a ' + trim(design.borehole_diameter_in) + '" hole');
    if (design.sanitary_seal) {
      callout(design.sanitary_seal[0], design.sanitary_seal[1],
        'Cement sanitary seal ' + S.fmt(design.sanitary_seal[0], 1) + '–' +
        S.fmt(design.sanitary_seal[1], 1) + ' m');
    }
    if (design.backfill && design.backfill[1] > design.backfill[0]) {
      callout(design.backfill[0], design.backfill[1],
        'Backfill ' + S.fmt(design.backfill[0], 1) + '–' +
        S.fmt(design.backfill[1], 1) + ' m');
    }
    if (design.gravel_pack) {
      callout(design.gravel_pack[0], design.gravel_pack[1],
        'Gravel pack ' + S.fmt(design.gravel_pack[0], 1) + '–' +
        S.fmt(design.gravel_pack[1], 1) + ' m');
    }
    segments.forEach(function (seg) {
      var label = seg.kind === 'screen'
        ? 'Screen ' + S.fmt(seg.top_m, 1) + '–' + S.fmt(seg.bottom_m, 1) + ' m' +
          (design.screen_slot_mm ? ', ' + trim(design.screen_slot_mm) + ' mm slot' : '')
        : seg.kind === 'sump'
          ? 'Sump ' + S.fmt(seg.top_m, 1) + '–' + S.fmt(seg.bottom_m, 1) + ' m'
          : 'Plain casing ' + S.fmt(seg.top_m, 1) + '–' + S.fmt(seg.bottom_m, 1) + ' m';
      callout(seg.top_m, seg.bottom_m, label);
    });
    if (intake !== null) {
      callout(intake, intake, 'Pump intake ' + S.fmt(intake, intake % 1 ? 1 : 0) + ' m');
    }

    var wrapped = callouts.map(function (c) {
      return { anchor: c.anchor, lines: wrapText(c.text, labelMaxW, 9.5) };
    });
    var tallest = wrapped.reduce(function (m, c) { return Math.max(m, c.lines.length); }, 1);
    var gap = Math.max(15, tallest * 11 + 3);
    stackLabels(wrapped, gap, groundY - stickPx + 6, bottomY - 2)
      .forEach(function (item) {
        var e = item.entry;
        var midY = item.y;
        svg.appendChild(polyline([
          [boreX1 + 3, e.anchor], [labelX - 22, e.anchor],
          [labelX - 6, midY],
        ], { stroke: p.axis, 'stroke-width': 0.8 }));
        e.lines.forEach(function (line, i) {
          svg.appendChild(svgEl('text', {
            x: labelX, y: midY + 3.4 - (e.lines.length - 1) * 5.5 + i * 11,
            'font-size': 9.5, fill: p.inkSoft, text: line,
          }));
        });
      });

    /* --------------------------------------------------------- the legend */
    var legendTop = height - legendH + 4;
    svg.appendChild(svgEl('line', {
      x1: 16, y1: legendTop - 6, x2: width - 16, y2: legendTop - 6,
      stroke: p.grid, 'stroke-width': 1,
    }));
    legendItems.forEach(function (item, i) {
      var col = i % legendCols, row = Math.floor(i / legendCols);
      var x = 16 + col * legendColW;
      var y = legendTop + 12 + row * legendRowH;
      svg.appendChild(svgEl('rect', {
        x: x, y: y - 8, width: 11, height: 11, rx: 1.5,
        fill: item.fill ? fills[item.fill] : item.colour,
        stroke: p.axis, 'stroke-width': 0.6,
      }));
      svg.appendChild(svgEl('text', {
        x: x + 17, y: y + 1, 'font-size': 9.5, fill: p.inkSoft,
        text: ellipsise(item.label, legendColW - 26, 9.5),
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
        /* wrapped rather than cut at a character count, and in whichever of
         * black or white stays readable on this fill - white on the sand
         * colours was not */
        var lines = wrapText(String(unit.description || ''), lithW - 12, 9);
        var fits = Math.floor((h - 2) / 10.5);
        if (lines.length > fits) {
          lines = lines.slice(0, Math.max(1, fits));
          lines[lines.length - 1] = ellipsise(lines[lines.length - 1] + ' …',
            lithW - 12, 9);
        }
        var ink = unit.aquifer ? p.ink : readableInk(colour);
        lines.forEach(function (line, k) {
          svg.appendChild(svgEl('text', {
            x: lithX + 6, y: y0 + h / 2 + 3.5 - (lines.length - 1) * 5.25 + k * 10.5,
            'font-size': 9, fill: ink, text: line,
          }));
        });
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
        /* "Nitrate (as NO3)" and "Total hardness" both fit; the point is that
         * nothing is cut in the middle of a word without saying so */
        text: ellipsise(String(row.parameter), left - 20, 9.5),
      }));
      /* Coloured by status, not by the ratio alone: a national limit is law
       * rather than taste, and a row the toolkit could not grade is neither a
       * pass nor a failure - drawing it in the "good" colour would be the same
       * fail-open the verdict used to have. */
      var status = String(row.status || '');
      var bad = status === 'exceeds_health' || status === 'exceeds_national';
      var warn = status === 'exceeds_aesthetic';
      var ungraded = status === 'indeterminate' || status === 'not_measured' ||
        row.evaluable === false;
      var fill = bad ? p.critical : (warn ? p.warning : (ungraded ? p.muted : p.good));
      svg.appendChild(svgEl('rect', {
        x: left, y: y + 3, width: Math.max(1, fx(row.ratio) - left), height: 12,
        rx: 2, fill: fill, opacity: (bad || warn) ? 0.9 : 0.75,
      }));
      /* the value goes to the right of the bar, or inside its end when there
       * is no longer room to the right of it */
      var valueText = (row.value === null ? '—' : row.value) + ' ' + (row.unit || '');
      var valueW = textWidth(valueText, 9);
      var barEnd = fx(row.ratio);
      var outside = barEnd + 5 + valueW <= width - 8;
      svg.appendChild(svgEl('text', {
        x: outside ? barEnd + 5 : barEnd - 5, y: y + 13, 'font-size': 9,
        'text-anchor': outside ? 'start' : 'end',
        fill: outside ? p.inkSoft : '#FFFFFF',
        text: valueText,
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
    var barH = 26, gap = 14;
    var height = 62 + data.length * (barH + gap);
    var labelW = 160;
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

    /* room for the widest amount, so the longest bar's label has somewhere to
     * go instead of being written past the right edge of the figure */
    var amounts = data.map(function (row) {
      return S.money(row[1], 0) + '  (' +
        (total ? (100 * row[1] / total).toFixed(0) : '0') + '%)';
    });
    var amountW = amounts.reduce(function (m, text) {
      return Math.max(m, textWidth(text, 11.5));
    }, 0);
    var plotW = width - labelW - amountW - 34;

    data.forEach(function (row, i) {
      var y = 42 + i * (barH + gap);
      var w = maxV > 0 ? (row[1] / maxV) * plotW : 0;
      /* the stage names run to "Development and completion", which written
       * out at this size is wider than the gutter it was written into */
      var label = mode === 'stage' ? row[0] : S.titleCase(row[0]);
      var lines = wrapText(label, labelW - 14, 11.5);
      if (lines.length > 2) {
        lines = [lines[0], ellipsise(lines.slice(1).join(' '), labelW - 14, 11.5)];
      }
      lines.forEach(function (line, k) {
        svg.appendChild(svgEl('text', {
          x: labelW - 10, y: y + barH / 2 + 4.5 - (lines.length - 1) * 6 + k * 12,
          'text-anchor': 'end', 'font-size': 11.5, fill: p.inkSoft, text: line,
        }));
      });
      /* rounded data end anchored to the baseline. One hue: the bars are a
       * ranking of one quantity, and giving each its own colour would say
       * they are different kinds of thing. */
      svg.appendChild(svgEl('path', {
        d: roundedBar(labelW, y, Math.max(w, 2), barH, 4),
        fill: p.accent,
      }));
      svg.appendChild(svgEl('text', {
        x: labelW + w + 10, y: y + barH / 2 + 4, 'font-size': 11.5, fill: p.ink,
        text: amounts[i],
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

  /* --------------------------------------------------------- point in shape */

  function pointInRing(lon, lat, ring) {
    var inside = false;
    for (var i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      var xi = ring[i][0], yi = ring[i][1], xj = ring[j][0], yj = ring[j][1];
      if ((yi > lat) !== (yj > lat) &&
          lon < (xj - xi) * (lat - yi) / ((yj - yi) || 1e-12) + xi) {
        inside = !inside;
      }
    }
    return inside;
  }

  function pointInFeature(lon, lat, geometry) {
    if (!geometry) return false;
    function inPolygon(rings) {
      if (!rings.length || !pointInRing(lon, lat, rings[0])) return false;
      for (var h = 1; h < rings.length; h++) {
        if (pointInRing(lon, lat, rings[h])) return false;   /* in a hole */
      }
      return true;
    }
    if (geometry.type === 'Polygon') return inPolygon(geometry.coordinates);
    if (geometry.type === 'MultiPolygon') {
      return geometry.coordinates.some(inPolygon);
    }
    return false;
  }

  /* A polygon can cover a corner of the window without any sample point
   * landing on it. Its own vertices give it away. */
  function anyVertexInside(geometry, box) {
    var found = false;
    function scan(coords) {
      if (found) return;
      if (typeof coords[0] === 'number') {
        if (coords[0] >= box[0] && coords[0] <= box[2] &&
            coords[1] >= box[1] && coords[1] <= box[3]) found = true;
        return;
      }
      coords.forEach(scan);
    }
    if (geometry && geometry.coordinates) scan(geometry.coordinates);
    return found;
  }

  /* ------------------------------------------------------------- furniture */

  var GRATICULE_STEPS = [0.02, 0.05, 0.1, 0.25, 0.5, 1, 2, 5];

  function graticuleStep(span) {
    for (var i = 0; i < GRATICULE_STEPS.length; i++) {
      if (span / GRATICULE_STEPS[i] <= 5) return GRATICULE_STEPS[i];
    }
    return GRATICULE_STEPS[GRATICULE_STEPS.length - 1];
  }

  function degreeLabel(value, axis) {
    var hemi = axis === 'lat' ? (value < 0 ? 'S' : 'N') : (value < 0 ? 'W' : 'E');
    var v = Math.abs(value);
    var text = v >= 10 ? v.toFixed(1) : v.toFixed(2);
    return text.replace(/\.?0+$/, '') + '°' + hemi;
  }

  var SCALE_STEPS_KM = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000];

  function drawMapFurniture(svg, project, rect, p, options) {
    var opts = options || {};
    var b = project.bounds;

    /* graticule, labelled where it meets the neatline */
    if (opts.graticule !== false) {
      var g = svgEl('g', { 'aria-hidden': 'true' });
      var lonStep = graticuleStep(b.lonMax - b.lonMin);
      var latStep = graticuleStep(b.latMax - b.latMin);
      var lon = Math.ceil(b.lonMin / lonStep) * lonStep;
      for (; lon <= b.lonMax + 1e-9; lon += lonStep) {
        var x = project(lon, b.latMax)[0];
        if (x < rect.x + 14 || x > rect.x + rect.w - 14) continue;
        g.appendChild(svgEl('line', {
          x1: x, y1: rect.y, x2: x, y2: rect.y + rect.h,
          stroke: p.grid, 'stroke-width': 0.7, 'stroke-dasharray': '2 4',
        }));
        g.appendChild(svgEl('text', {
          x: x, y: rect.y + rect.h + 11, 'text-anchor': 'middle',
          'font-size': 8.5, fill: p.muted, text: degreeLabel(lon, 'lon'),
        }));
      }
      var lat = Math.ceil(b.latMin / latStep) * latStep;
      for (; lat <= b.latMax + 1e-9; lat += latStep) {
        var y = project(b.lonMin, lat)[1];
        if (y < rect.y + 12 || y > rect.y + rect.h - 12) continue;
        g.appendChild(svgEl('line', {
          x1: rect.x, y1: y, x2: rect.x + rect.w, y2: y,
          stroke: p.grid, 'stroke-width': 0.7, 'stroke-dasharray': '2 4',
        }));
        g.appendChild(svgEl('text', {
          x: rect.x - 4, y: y + 3, 'text-anchor': 'end',
          'font-size': 8.5, fill: p.muted, text: degreeLabel(lat, 'lat'),
        }));
      }
      svg.appendChild(g);
    }

    /* neatline */
    svg.appendChild(svgEl('rect', {
      x: rect.x, y: rect.y, width: rect.w, height: rect.h,
      fill: 'none', stroke: p.axis, 'stroke-width': 1,
    }));

    /* scale bar: a round number of kilometres, 60-150 px long */
    if (opts.scaleBar !== false && isFinite(project.metresPerPx)) {
      var target = 110 * project.metresPerPx / 1000;
      var km = SCALE_STEPS_KM[SCALE_STEPS_KM.length - 1];
      for (var i = 0; i < SCALE_STEPS_KM.length; i++) {
        if (SCALE_STEPS_KM[i] >= target) { km = SCALE_STEPS_KM[i]; break; }
      }
      var barPx = km * 1000 / project.metresPerPx;
      if (barPx > rect.w * 0.6) { km /= 2; barPx /= 2; }
      var bx = rect.x + 10, by = rect.y + rect.h - 14;
      var farLabel = km >= 1 ? km + ' km' : (km * 1000) + ' m';
      svg.appendChild(svgEl('rect', {
        x: bx - 6, y: by - 20, width: barPx + 12 + textWidth(farLabel, 8.5) / 2,
        height: 26, rx: 3, fill: p.surface, 'fill-opacity': 0.88,
      }));
      /* two blocks, so the bar can be halved by eye */
      [0, 1].forEach(function (half) {
        svg.appendChild(svgEl('rect', {
          x: bx + half * barPx / 2, y: by - 4, width: barPx / 2, height: 4,
          fill: half ? p.surface : p.ink, stroke: p.ink, 'stroke-width': 0.7,
        }));
      });
      svg.appendChild(svgEl('text', {
        x: bx, y: by - 8, 'text-anchor': 'middle', 'font-size': 8.5,
        fill: p.inkSoft, text: '0',
      }));
      svg.appendChild(svgEl('text', {
        x: bx + barPx, y: by - 8, 'text-anchor': 'middle', 'font-size': 8.5,
        fill: p.inkSoft, text: farLabel,
      }));
    }

    /* north arrow */
    if (opts.northArrow !== false) {
      var nx = rect.x + rect.w - 18, ny = rect.y + 14;
      svg.appendChild(svgEl('rect', {
        x: nx - 11, y: ny - 10, width: 22, height: 34, rx: 3,
        fill: p.surface, 'fill-opacity': 0.86,
      }));
      svg.appendChild(svgEl('path', {
        d: 'M' + nx + ' ' + (ny - 8) + 'L' + (nx + 6) + ' ' + (ny + 9) +
           'L' + nx + ' ' + (ny + 4) + 'L' + (nx - 6) + ' ' + (ny + 9) + 'Z',
        fill: p.inkSoft,
      }));
      svg.appendChild(svgEl('text', {
        x: nx, y: ny + 21, 'text-anchor': 'middle', 'font-size': 9,
        'font-weight': 620, fill: p.inkSoft, text: 'N',
      }));
    }
  }

  /* The legend is measured before the map is laid out, because how many rows
   * it needs is what decides how much height the map itself can have. */
  function mapLegendLayout(items, width, size) {
    var fontSize = size || 9.5;
    var longest = items.reduce(function (m, it) {
      return Math.max(m, textWidth(it.label, fontSize));
    }, 0);
    var cols = longest + 24 <= (width - 12) / 3 ? 3
      : longest + 24 <= (width - 12) / 2 ? 2 : 1;
    var colW = (width - 12) / cols;
    var rows = items.map(function (item) {
      return { item: item, lines: wrapText(item.label, colW - 24, fontSize) };
    });
    var perCol = Math.ceil(rows.length / cols);
    var lineH = 12.5;
    var height = 0;
    for (var c = 0; c < cols; c++) {
      var h = 0;
      rows.slice(c * perCol, (c + 1) * perCol).forEach(function (row) {
        h += row.lines.length * lineH + 4;
      });
      height = Math.max(height, h);
    }
    return { rows: rows, cols: cols, colW: colW, perCol: perCol,
      lineH: lineH, fontSize: fontSize, height: height + 8 };
  }

  function drawMapLegend(svg, layout, x, y, p, title) {
    if (title) {
      svg.appendChild(svgEl('text', {
        x: x, y: y - 4, 'font-size': 9, fill: p.muted,
        'letter-spacing': '0.04em', text: title,
      }));
    }
    layout.rows.forEach(function (row, i) {
      var col = Math.floor(i / layout.perCol);
      var within = i % layout.perCol;
      var top = y + 4;
      for (var k = col * layout.perCol; k < col * layout.perCol + within; k++) {
        top += layout.rows[k].lines.length * layout.lineH + 4;
      }
      var cx = x + col * layout.colW;
      var item = row.item;
      if (item.kind && item.kind !== 'swatch') {
        svg.appendChild(marker(cx + 5.5, top + 5, item.kind, item.colour,
          p.surface, 4.5));
      } else {
        svg.appendChild(svgEl('rect', {
          x: cx, y: top, width: 11, height: 11, rx: 1.5,
          fill: item.colour, stroke: p.axis, 'stroke-width': 0.6,
        }));
      }
      row.lines.forEach(function (line, li) {
        svg.appendChild(svgEl('text', {
          x: cx + 17, y: top + 9 + li * layout.lineH,
          'font-size': layout.fontSize, fill: p.inkSoft, text: line,
        }));
      });
    });
  }

  /* Lays out title, map frame, legend and credit, and hands back the frame so
   * the caller only has to draw its own layer into it. */
  function mapCanvas(spec, legendItems, extentFeatures) {
    var p = palette();
    var width = spec.width || 620;
    var height = spec.height || 520;
    var titleH = spec.title ? 26 : 8;
    var creditLines = spec.credit
      ? wrapText(spec.credit, width - 28, 8.5) : [];
    var creditH = creditLines.length ? creditLines.length * 11 + 6 : 0;

    function frameFor(legendH) {
      return {
        x: 42, y: titleH + 6, w: width - 56,
        h: height - titleH - 6 - legendH - creditH - 22,
      };
    }
    function layoutFor(items) {
      return items && items.length ? mapLegendLayout(items, width - 28) : null;
    }
    function heightOf(l) { return l ? l.height + (spec.legendTitle ? 14 : 4) : 0; }

    var rect, legend, items;
    if (typeof legendItems === 'function') {
      rect = frameFor(0);
      items = legendItems(projectionInto(extentFeatures, rect, 4), rect);
      legend = layoutFor(items);
      rect = frameFor(heightOf(legend));
      items = legendItems(projectionInto(extentFeatures, rect, 4), rect);
      legend = layoutFor(items);
      rect = frameFor(heightOf(legend));
    } else {
      legend = layoutFor(legendItems);
      rect = frameFor(heightOf(legend));
    }
    var legendH = heightOf(legend);

    var svg = svgEl('svg', {
      viewBox: '0 0 ' + width + ' ' + height, width: '100%', xmlns: NS,
      'font-family': FONT, role: 'img', 'aria-label': spec.title || 'map',
    });
    svg.appendChild(svgEl('rect', { width: width, height: height, fill: p.surface }));
    if (spec.title) {
      svg.appendChild(svgEl('text', {
        x: 14, y: 19, 'font-size': 13, 'font-weight': 620, fill: p.ink,
        text: ellipsise(spec.title, width - 28, 13),
      }));
    }
    /* the ground the layers are drawn on: anything left showing is a gap in
     * the data, and the legend says so */
    svg.appendChild(svgEl('rect', {
      x: rect.x, y: rect.y, width: rect.w, height: rect.h, fill: MAP_NO_DATA,
    }));

    var project = projectionInto(extentFeatures, rect, 4);
    var layer = svgEl('g');
    svg.appendChild(layer);

    return {
      svg: svg, layer: layer, project: project, rect: rect, palette: p,
      width: width, height: height,
      finish: function (options) {
        drawMapFurniture(svg, project, rect, p, options || {});
        var y = rect.y + rect.h + 18 + (spec.legendTitle ? 12 : 0);
        if (legend) drawMapLegend(svg, legend, 14, y, p, spec.legendTitle);
        if (creditLines.length) {
          creditLines.forEach(function (line, i) {
            svg.appendChild(svgEl('text', {
              x: 14, y: height - 8 - (creditLines.length - 1 - i) * 11,
              'font-size': 8.5, fill: p.muted, text: line,
            }));
          });
        }
        return svg;
      },
    };
  }

  function drawMapPoints(canvas, points) {
    var p = canvas.palette;
    (points || []).forEach(function (point) {
      var pt = canvas.project(point.lon, point.lat);
      if (pt[0] < canvas.rect.x - 4 || pt[0] > canvas.rect.x + canvas.rect.w + 4 ||
          pt[1] < canvas.rect.y - 4 || pt[1] > canvas.rect.y + canvas.rect.h + 4) return;
      canvas.svg.appendChild(marker(pt[0], pt[1], point.kind || 'circle',
        point.colour || p.secondary, p.surface, point.size || 5));
      if (point.label) {
        var anchor = pt[0] > canvas.rect.x + canvas.rect.w * 0.72 ? 'end' : 'start';
        canvas.svg.appendChild(svgEl('text', {
          x: pt[0] + (anchor === 'end' ? -10 : 10), y: pt[1] + 3.5,
          'text-anchor': anchor, 'font-size': 10, fill: p.ink,
          stroke: p.surface, 'stroke-width': 3, 'paint-order': 'stroke',
          text: point.label,
        }));
      }
    });
  }

  /* ------------------------------------------------------------ choropleth */

  function choropleth(spec) {
    var features = spec.features || [];
    var values = features.map(spec.value).filter(function (v) {
      return typeof v === 'number' && isFinite(v);
    });
    var breaks = spec.breaks || quantileBreaks(values, 5);
    var pal = palette();
    /* One colour per class, sampled across the whole ramp. Slicing a fixed
     * window off it gave fewer colours than classes as soon as the breaks
     * were supplied rather than computed, and the top classes then shared a
     * colour while the legend still listed them apart. */
    var classes = breaks.length + 1;
    var ramp = [];
    for (var c = 0; c < classes; c++) {
      var t = classes === 1 ? 0.5 : c / (classes - 1);
      ramp.push(pal.seq[Math.round(t * (pal.seq.length - 1))]);
    }

    var legendItems = [];
    if (spec.legend !== false && breaks.length) {
      ramp.forEach(function (colour, i) {
        var lo = i === 0 ? null : breaks[i - 1];
        var hi = i < breaks.length ? breaks[i] : null;
        legendItems.push({
          colour: colour,
          label: lo === null ? 'under ' + S.sig(hi, 3)
            : (hi === null ? S.sig(lo, 3) + ' and over'
              : S.sig(lo, 3) + ' to ' + S.sig(hi, 3)),
        });
      });
      if (features.some(function (f) { return classify(spec.value(f), breaks) === null; })) {
        legendItems.push({ colour: '#D8D4CB', label: 'no figure recorded' });
      }
    }

    var canvas = mapCanvas(spec, legendItems, features);
    features.forEach(function (feature) {
      var v = spec.value(feature);
      var cls = classify(v, breaks);
      canvas.layer.appendChild(svgEl('path', {
        d: geometryPath(feature.geometry, canvas.project),
        fill: cls === null ? '#D8D4CB' : ramp[Math.min(cls, ramp.length - 1)],
        stroke: canvas.palette.surface, 'stroke-width': 0.8,
        'aria-label': (spec.name ? spec.name(feature) : '') +
          (v === null || v === undefined ? '' : ': ' + S.sig(v, 3)),
      }, [svgEl('title', {
        text: (spec.name ? spec.name(feature) : '') +
          (v === null || v === undefined ? '' : ': ' + S.sig(v, 3)),
      })]));
    });
    drawMapPoints(canvas, spec.points);
    return canvas.finish();
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

  /* ---------------------------------------------------------- thematic map */

  var clipSeq = 0;

  /* A categorical polygon layer - geology or aquifer productivity - clipped
   * to a window around the site when there is one.
   *
   * The layers carry their own published colours, so the map reads the same
   * way the source sheet does rather than being recoloured here.
   *
   * The legend names the units that actually cover ground inside the window,
   * found by sampling the window on a grid. Selecting by bounding box, which
   * is how the polygons are chosen for drawing, would put a unit in the
   * legend whose only claim on the window is that its bounding box reaches
   * across the country. */
  function thematicMap(spec) {
    var key = spec.key || 'unit';
    var all = spec.features || [];
    var window_ = spec.window || null;

    var features = all, clip = null;
    if (window_) {
      var dLat = window_.radiusKm / 110.574;
      var dLon = window_.radiusKm /
        (111.320 * Math.max(Math.cos(window_.lat * Math.PI / 180), 1e-6));
      clip = [window_.lon - dLon, window_.lat - dLat,
        window_.lon + dLon, window_.lat + dLat];
      features = all.filter(function (feature) {
        var b = featureBounds([feature]);
        return isFinite(b.lonMin) && b.lonMin <= clip[2] && b.lonMax >= clip[0] &&
          b.latMin <= clip[3] && b.latMax >= clip[1];
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

    /* Which units are really in view. The frame shows more than the window
     * asked for - the projection letterboxes it - so the box to sample is
     * the one the frame actually covers, which mapCanvas works out. */
    function legendFor(project) {
      var box = project.visibleBox();
      var seen = [], gaps = false;
      function note(feature) {
        var props = feature.properties || {};
        var label = String(props[key] || 'unclassified');
        if (!seen.some(function (s) { return s.label === label; })) {
          seen.push({ label: label, colour: props.color || palette().neutral });
        }
      }
      var STEPS = 22;
      for (var i = 0; i <= STEPS; i++) {
        for (var j = 0; j <= STEPS; j++) {
          var lon = box[0] + (box[2] - box[0]) * i / STEPS;
          var lat = box[1] + (box[3] - box[1]) * j / STEPS;
          var hit = null;
          for (var f = 0; f < features.length; f++) {
            if (pointInFeature(lon, lat, features[f].geometry)) {
              hit = features[f]; break;
            }
          }
          if (!hit) { gaps = true; continue; }
          note(hit);
        }
      }
      /* a unit can cross a corner without a sample landing on it */
      features.forEach(function (feature) {
        if (anyVertexInside(feature.geometry, box)) note(feature);
      });
      seen.sort(function (a, b) { return a.label.localeCompare(b.label); });
      var items = seen.slice();
      if (gaps) items.push({ label: 'not mapped', colour: MAP_NO_DATA });
      (spec.points || []).forEach(function (point) {
        if (!point.label) return;
        items.push({
          label: point.legend || point.label, kind: point.kind || 'diamond',
          colour: point.colour || palette().secondary,
        });
      });
      return items;
    }

    var canvas = mapCanvas(spec, legendFor, extent);
    var p = canvas.palette;

    clipSeq += 1;
    var clipId = 'gwt-clip-' + clipSeq;
    var defs = svgEl('defs');
    defs.appendChild(svgEl('clipPath', { id: clipId }, [svgEl('rect', {
      x: canvas.rect.x, y: canvas.rect.y,
      width: canvas.rect.w, height: canvas.rect.h,
    })]));
    canvas.svg.insertBefore(defs, canvas.svg.firstChild);
    canvas.layer.setAttribute('clip-path', 'url(#' + clipId + ')');

    features.forEach(function (feature) {
      var props = feature.properties || {};
      canvas.layer.appendChild(svgEl('path', {
        d: geometryPath(feature.geometry, canvas.project),
        fill: props.color || p.neutral, 'fill-opacity': 0.85,
        stroke: p.surface, 'stroke-width': 0.5,
      }, [svgEl('title', { text: String(props[key] || 'unclassified') })]));
    });
    (spec.context || []).forEach(function (feature) {
      canvas.layer.appendChild(svgEl('path', {
        d: geometryPath(feature.geometry, canvas.project), fill: 'none',
        stroke: p.axis, 'stroke-width': 0.8,
      }));
    });
    drawMapPoints(canvas, (spec.points || []).map(function (pt) {
      return Object.assign({ kind: 'diamond', size: 6.5 }, pt);
    }));
    return canvas.finish();
  }

  /* -------------------------------------------------------------- site map */

  /* Boundaries as context, survey points as the data. Without a position the
   * map is still drawn - the district is still worth showing - but it says in
   * the legend that the site is not on it, because a locator map with no
   * locator on it is the kind of figure that gets signed off by mistake. */
  function siteMap(spec) {
    var context = spec.context || [];
    var points = spec.points || [];
    var legendItems = (spec.legendItems || []).slice();
    if (!legendItems.length) {
      points.forEach(function (point) {
        legendItems.push({
          label: point.legend || point.label || 'Site',
          colour: point.colour || palette().secondary,
          kind: point.kind || 'diamond',
        });
      });
    }
    if (!points.length) {
      legendItems.push({ label: 'no position recorded for this site',
        colour: MAP_NO_DATA });
    }

    var extent = context.length ? context : points.map(function (pt) {
      return { geometry: { type: 'Polygon', coordinates: [[[pt.lon, pt.lat]]] } };
    });
    /* a lone point projects to a degenerate extent; give it a window it can
     * actually be seen in */
    if (!context.length && points.length) {
      var pad = (spec.radiusKm || 25) / 110.574;
      extent = [{ geometry: { type: 'Polygon', coordinates: [[
        [points[0].lon - pad, points[0].lat - pad],
        [points[0].lon + pad, points[0].lat - pad],
        [points[0].lon + pad, points[0].lat + pad],
        [points[0].lon - pad, points[0].lat + pad],
      ]] } }];
    }

    var canvas = mapCanvas(spec, legendItems, extent);
    var p = canvas.palette;
    context.forEach(function (feature) {
      canvas.layer.appendChild(svgEl('path', {
        d: geometryPath(feature.geometry, canvas.project),
        fill: spec.contextFill ? spec.contextFill(feature) : '#EDEAE3',
        stroke: p.axis, 'stroke-width': 0.7,
      }, [svgEl('title', {
        text: String((feature.properties || {}).name ||
          (feature.properties || {}).shapeName || ''),
      })]));
    });
    drawMapPoints(canvas, points.map(function (pt) {
      return Object.assign({ kind: 'diamond', size: 6.5 }, pt);
    }));
    return canvas.finish();
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
        /* the rasteriser can fail - an unloadable font, a tainted canvas -
         * and with no handler the button simply did nothing */
        toPng(svg, { scale: 2 }).then(function (png) {
          return fetch(png.dataUrl).then(function (r) { return r.blob(); })
            .then(function (blob) {
              S.download((opts.filename || S.slug(caption || 'figure')) + '.png', blob);
            });
        }).catch(function (e) {
          S.toast('Could not export this figure as a PNG: ' + e.message, 'error');
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
    mapProjection: mapProjection, projectionInto: projectionInto,
    geometryPath: geometryPath, quantileBreaks: quantileBreaks,
    pointInFeature: pointInFeature,
    textWidth: textWidth, wrapText: wrapText, ellipsise: ellipsise,
    stackLabels: stackLabels,
    toPng: toPng, downloadSvg: download, figure: figure,
  };
}(typeof window !== 'undefined' ? window : globalThis));

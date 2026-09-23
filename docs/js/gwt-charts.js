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

  /* A figure bound for a .docx is painted for paper, not for the screen it
   * was built on.
   *
   * Every chart takes its colours from the live CSS tokens at the moment it
   * is constructed, and the app's default theme is dark, so a client opening
   * a report got maps, sections and borehole drawings rasterised white on
   * black. The fallbacks below are the stylesheet's own light values, so a
   * chart built while this flag is set is a chart built for print, whatever
   * the reader of the app is looking at. Set it around the figure building,
   * not around the rasterising: the colours are already in the SVG by then.
   *
   * It is a count, not a switch. Each build turns it on and off again in its
   * own `finally`, and builds overlap - two report cards clicked one after
   * the other run at once - so a switch was turned off by whichever build
   * finished first while the other was still drawing, and that one's
   * remaining figures went into its document on the dark ground. The print
   * palette holds until the last build that asked for it is done. */
  var printDepth = 0;

  function usePrintPalette(on) {
    printDepth = on ? printDepth + 1 : Math.max(0, printDepth - 1);
  }

  function token(name, fallback) {
    if (printDepth > 0) return fallback;
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

  /* A frame's title, and how much wider it is than textWidth() thinks.
   *
   * textWidth models the regular weight and a title is drawn at weight 600.
   * Measured against the browser over the titles these figures actually
   * carry, the semi-bold line runs a fifth to a quarter past the estimate, so
   * a title wrapped against the plain estimate still ran off the page. A
   * title measured at this multiple wraps early rather than late, which costs
   * a line of white space and never loses a word. */
  var TITLE_SIZE = 13;
  var TITLE_BOLD_WIDTH = 1.25;

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
      /* A figure whose fill carries the reading rules its own grid off: the
       * geoelectric section and the layer pseudo-section call ax.grid(False)
       * in the Python because a rule across a coloured layer column reads as
       * a layer boundary, and the one thing a section may not do is invent a
       * boundary. The tick numbers stay either way. */
      if (spec.grid !== false) {
        grid.appendChild(svgEl('line', {
          x1: x, y1: margin.top, x2: x, y2: margin.top + plotH,
          stroke: p.grid, 'stroke-width': 1,
        }));
      }
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
      if (spec.grid !== false) {
        grid.appendChild(svgEl('line', {
          x1: margin.left, y1: y, x2: margin.left + plotW, y2: y,
          stroke: p.grid, 'stroke-width': 1,
        }));
      }
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
      /* A title wider than the figure is cut off at the edge of the viewBox,
       * and what is cut off is the end of the sentence. The geoelectric
       * section builds its title out of the survey and carries the caveat on
       * the tail of it - "(soundings up to 65 m off the line)" - so the
       * browser printed a section that claimed to be along a line and
       * silently dropped the words saying it was not. matplotlib grows the
       * figure until the whole title fits; a viewBox cannot grow, so a caller
       * whose title comes from the data passes titleWidth and the title wraps
       * onto as many lines as it needs. The caller leaves room for them: this
       * draws from y=18 down, into the top margin it was given. */
      var titleLines = spec.titleWidth
        ? wrapText(spec.title, spec.titleWidth, TITLE_SIZE * TITLE_BOLD_WIDTH)
        : [spec.title];
      titleLines.forEach(function (line, i) {
        svg.appendChild(svgEl('text', {
          x: margin.left, y: 18 + i * 16, 'font-size': TITLE_SIZE,
          'font-weight': 600, fill: p.ink, text: line,
        }));
      });
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
    if (kind === 'star') {
      /* five points, outer radius r * 1.5, inner radius r * 0.6 */
      var d = '', k;
      for (k = 0; k < 10; k++) {
        var radius = (k % 2 === 0) ? r * 1.5 : r * 0.6;
        var angle = -Math.PI / 2 + k * Math.PI / 5;
        d += (k === 0 ? 'M' : 'L') + (x + radius * Math.cos(angle)).toFixed(2) + ' ' +
          (y + radius * Math.sin(angle)).toFixed(2);
      }
      return svgEl('path', {
        d: d + 'Z', fill: colour, stroke: ring, 'stroke-width': 1.6,
        'stroke-linejoin': 'round',
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
      xLabel: String(result.array_type || '').indexOf('wenner') === 0
        ? 'a (m)' : 'AB/2 (m)',
      yLabel: 'Apparent resistivity (ohm-m)',
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
   * so the legend names the class. The table is the engine's
   * (groundwater/design/lithology.py, C.lithologyClass): this file kept a
   * second one, and the same interval was "clay and saprolite" on the
   * drawing, "saprolite" in the report and "fresh basement" on the Depth
   * Spine. One table, so every figure calls a log the same thing. */
  function lithologyClass(description) {
    var klass = C.lithologyClass(description);
    return { key: klass.key, label: klass.label, colour: klass.colour, hatch: klass.hatch };
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

    /* 5.0 -> 5, 6.5 -> 6.5: a diameter is quoted the way it is stamped, and
     * a depth prints as the Python drawing's :g does (14.5, not 14.0) */
    var formatG = C.formatG;

    var depth = design.total_depth_m || 1;
    var stickup = design.stickup_m || 0;
    /* a design's pump is where the pump should go and its screens are where
     * the rules put them; only an as-built record can say where they are */
    var asBuilt = !!design.as_built;
    var swl = (design.static_water_level_m === null ||
      design.static_water_level_m === undefined) ? null : design.static_water_level_m;

    /* ------------------------------------------------------------ colours */
    var COLOUR = {
      gravel: '#D9C89A', gravelMark: '#9C8A55',
      stabiliser: '#E3D3A4', stabiliserMark: '#A0905E',
      formation: '#F4F1EA',
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
    /* the log split into bands by the engine (groundwater/design/lithology.py):
     * a fracture zone the driller named with its depths is a band at those
     * depths, not a hatch across the five metres it was logged on, and the
     * rock around it is classed as what it is */
    var bands = litho.length ? C.lithologyBands(litho) : [];
    var lithoKeys = [];
    bands.forEach(function (band) {
      var label = band.label.toLowerCase();
      if (!lithoKeys.some(function (k) { return k.label === label; })) {
        lithoKeys.push({ label: label, colour: band.colour });
      }
    });
    /* The annulus below the seal, by what the design says it holds: a 19 mm
     * annulus used to be drawn and captioned as a gravel pack. */
    var FILL_STYLES = {
      'gravel pack': { label: 'gravel pack', colour: COLOUR.gravel, fill: 'gravel' },
      'formation stabiliser': {
        label: 'formation stabiliser', colour: COLOUR.stabiliser, fill: 'stabiliser',
      },
      'none': { label: 'no gravel pack (formation)', colour: COLOUR.formation },
    };
    var fillStyle = FILL_STYLES[design.annular_fill] || FILL_STYLES['gravel pack'];
    var hasSump = (design.segments || []).some(function (s) { return s.kind === 'sump'; });
    /* The construction materials come first because they are what the reader
     * is being asked to check; the formation classes follow. Each interval is
     * already named in the column beside it, so the legend explains what a
     * colour means rather than repeating twelve descriptions. The wording is
     * the Python drawing's. */
    var legendItems = [
      { label: fillStyle.label, colour: fillStyle.colour, fill: fillStyle.fill },
      { label: 'backfill', colour: COLOUR.backfill, fill: 'backfill' },
      { label: 'cement sanitary seal', colour: COLOUR.seal, fill: 'seal' },
      { label: 'plain casing', colour: COLOUR.casing },
      { label: 'screen', colour: COLOUR.screen },
    ];
    if (hasSump) legendItems.push({ label: 'sump', colour: COLOUR.sump });
    if (swl !== null) legendItems.push({ label: 'water in the casing', colour: COLOUR.water });
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
      'aria-label': (asBuilt ? 'As-built borehole record' : 'Borehole construction design') +
        ', drawn to scale with depth',
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
      /* finer than a gravel pack: placeable, but too thin to filter */
      stabiliser: {
        size: 6, background: COLOUR.stabiliser,
        marks: [
          svgEl('circle', { cx: 1.6, cy: 1.6, r: 0.85, fill: COLOUR.stabiliserMark }),
          svgEl('circle', { cx: 4.4, cy: 4.2, r: 0.85, fill: COLOUR.stabiliserMark }),
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
      text: opts.title ||
        (asBuilt ? 'As-built borehole record' : 'Borehole construction design'),
    }));
    /* the header block of the record sheet: the construction, and what the
     * drawing is. The log records no casing string, so a drawing built by
     * the rules says so on its own face. */
    var headerLines = [];
    if (opts.subtitle) headerLines.push(opts.subtitle);
    headerLines.push(
      'Construction: ' + formatG(design.borehole_diameter_in) + '" hole, ' +
      formatG(design.casing_diameter_in) + '" ' + (design.casing_material || 'uPVC') +
      '   ·   Drawing: ' + (asBuilt ? 'as built' : 'design generated from the log'));
    headerLines.forEach(function (line, i) {
      svg.appendChild(svgEl('text', {
        x: 16, y: titleY + 17 + i * 12, 'font-size': 10.5, fill: p.muted,
        text: ellipsise(line, width - 32, 10.5),
      }));
    });

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
      /* one rect per band with the band's colour, so a named fracture zone
       * sits at its own depths and the host rock around it keeps its own */
      bands.forEach(function (band) {
        var y0 = fy(Math.max(0, band.top_m));
        var y1 = fy(Math.min(band.bottom_m, depth));
        if (y1 <= y0) return;
        svg.appendChild(svgEl('rect', {
          x: lithX, y: y0, width: lithW, height: y1 - y0,
          fill: band.colour, stroke: '#FFFFFF', 'stroke-width': 0.8,
        }));
      });
      /* the driller's own words stay beside each logged interval; the ink
       * is chosen against the band that takes most of the interval */
      litho.forEach(function (interval) {
        var y0 = fy(Math.max(0, interval.top_m));
        var y1 = fy(Math.min(interval.bottom_m, depth));
        if (y1 <= y0) return;
        var colour = null, most = 0;
        bands.forEach(function (band) {
          var overlap = Math.min(band.bottom_m, interval.bottom_m) -
            Math.max(band.top_m, interval.top_m);
          if (overlap > most) { most = overlap; colour = band.colour; }
        });
        if (colour === null) colour = lithologyColour(interval.description);
        svg.appendChild(svgEl('rect', {
          x: lithX, y: y0, width: lithW, height: y1 - y0,
          fill: 'none', 'pointer-events': 'all',
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
    annulus(design.gravel_pack, fillStyle.fill ? fills[fillStyle.fill] : fillStyle.colour);
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
        text: 'SWL ' + C.pyFixed(swl, 2) + ' m', swl: true,
      });
    }
    (design.water_strikes_m || []).forEach(function (strike) {
      /* named for what it is: a bare "12 m" beside an arrow read as
       * anything from a casing joint to a sample depth */
      gutterEntries.push({
        anchor: fy(strike), colour: p.secondary,
        text: 'water strike ' + formatG(strike) + ' m',
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
    function span(top, bottom) {
      return formatG(top) + '-' + formatG(bottom) + ' m';
    }
    /* the diameters are in the header block; the callout keeps the stick-up */
    callout(-stickup, 0, 'stick-up ' + formatG(stickup) + ' m');
    if (design.sanitary_seal) {
      callout(design.sanitary_seal[0], design.sanitary_seal[1],
        'cement grout 0-' + formatG(design.sanitary_seal[1]) + ' m');
    }
    if (design.backfill && design.backfill[1] > design.backfill[0]) {
      callout(design.backfill[0], design.backfill[1],
        'backfill ' + span(design.backfill[0], design.backfill[1]));
    }
    if (design.gravel_pack) {
      callout(design.gravel_pack[0], design.gravel_pack[1],
        fillStyle.label + ' ' + span(design.gravel_pack[0], design.gravel_pack[1]));
    }
    segments.forEach(function (seg) {
      var label = seg.kind === 'screen'
        ? 'screen ' + span(seg.top_m, seg.bottom_m) +
          (design.screen_slot_mm ? ', ' + formatG(design.screen_slot_mm) + ' mm slot' : '')
        : seg.kind === 'sump'
          ? 'sump (sediment trap) ' + span(seg.top_m, seg.bottom_m) +
            ',\nbottom plug at ' + formatG(depth) + ' m'
          : 'plain casing ' + span(seg.top_m, seg.bottom_m);
      callout(seg.top_m, seg.bottom_m, label);
    });
    if (!hasSump) callout(depth, depth, 'bottom plug at ' + formatG(depth) + ' m');
    if (intake !== null) {
      /* a design's pump is where the pump should go; only an as-built
       * record can say where one is */
      callout(intake, intake, 'pump intake ' + formatG(intake) + ' m' +
        (asBuilt ? '' : ' (recommended)'));
    }

    /* a newline in a callout is a break the caller chose, so a unit is
     * never wrapped away from its number */
    var wrapped = callouts.map(function (c) {
      var lines = [];
      String(c.text).split('\n').forEach(function (part) {
        lines = lines.concat(wrapText(part, labelMaxW, 9.5));
      });
      return { anchor: c.anchor, lines: lines };
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
  /* The Python engine holds the same two in groundwater/mapping/cartography.py
   * as SEA and NOT_MAPPED; change one and change the other. They are kept
   * apart on purpose: sea and a hole in the source layer are different
   * things, and painting both the same tint is how a coverage gap along the
   * Bullom shore reads as ocean. */
  var MAP_SEA = '#D9E6EF';
  var MAP_NOT_MAPPED = '#EDEBE7';
  /* The land across the border, and the neutral fill under an administrative
   * map: carto.FOREIGN_LAND and carto.LAND in the Python engine. Guinea and
   * Liberia used to take the same blue as the Atlantic on every map, so a
   * site near the northern border looked like a site on the coast. */
  var MAP_FOREIGN_LAND = '#F2F0EC';
  var MAP_LAND = '#FBFAF8';

  /* A muted geological palette, keyed by the bundled USGS unit code. The
   * Python engine reads the same table in groundwater/mapping/cartography.py
   * as GEOLOGY_COLOURS; change one and change the other, or a report figure
   * and the screen figure of the same site come out different colours and a
   * reader holding both cannot line them up.
   *
   * The colours carried in the data are the USGS sheet's own - pure blue,
   * magenta, red - and three saturated hues fighting each other is what made
   * these read as a school atlas. The aquifer layer keeps its source colours,
   * because there the colour IS the classification.
   *
   * Each tint is at least 0.05 of relative luminance from every other and
   * from the sea, the paper and the not-mapped tone, so the units stay apart
   * in greyscale. The Bullom Group was 0.77 against a sea of 0.78 and
   * vanished into the Atlantic on a photocopy, which is how most of these
   * reports are actually read in the field. */
  var GEOLOGY_COLOURS = {
    pCm: '#CDBAC6', Pi: '#B7715C', Mi: '#CC9A86',
    O: '#9DB9A3', S: '#BCCDB6', Qe: '#E6D5A6', H2O: '#6F9BBF',
  };

  /* sRGB relative luminance, 0 (black) to 1 (white): what a photocopy keeps.
   * The same arithmetic as relative_luminance in the Python engine, so the
   * separation above can be held to the same figure on either side. */
  function relativeLuminance(colour) {
    var hex = String(colour).replace('#', '');
    var lin = [0, 2, 4].map(function (i) {
      var c = parseInt(hex.substr(i, 2), 16) / 255;
      return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
  }

  function unitColour(props, spec) {
    if (spec && spec.sourceColours) return props.color || palette().neutral;
    return GEOLOGY_COLOURS[props.glg] || props.color || palette().neutral;
  }

  /* Youngest first, oldest last, and the things that are not rocks after
   * both: the order a map key is read in, and _ERA_ORDER in the Python
   * engine. Anything the list does not name ranks after all of it. */
  var ERA_ORDER = ['Cenozoic', 'Mesozoic', 'Paleozoic', 'Precambrian',
    'Non-geological'];

  /* The era and the source code one key entry is ranked by. The geology
   * layer carries them as `era` and `glg`; the aquifer layer carries the
   * same two as `geology` and `code`, which is where load_hydrogeology reads
   * them from in the Python engine. Sorting the key alphabetically by label
   * instead put "Surface water" between two aquifer classes on the national
   * aquifer map, where the Python key ends on it. */
  function eraRank(props) {
    var found = ERA_ORDER.indexOf(props.era || props.geology || '');
    return found < 0 ? 99 : found;
  }

  function unitCode(props) {
    return String(props.glg || props.code || '');
  }

  /* Which crosswalk region a district belongs to, what the ground is for one
   * USGS class there, and which district a polygon lies in. They live in the
   * engine, gwt-core.js, because the geophysical report's geology paragraph
   * reads them too: the key on the map and the paragraph beside it name one
   * polygon one way, and the parity suite holds the paragraph to the
   * Python's. */
  var regionOf = C.lithologyRegionOf;
  var lithologyFor = C.lithologyFor;
  var unitDistrict = C.unitDistrict;

  /* Centroid of a ring, by the shoelace formula. */
  function ringCentroid(ring) {
    var area = 0, cx = 0, cy = 0, sx = 0, sy = 0;
    for (var i = 0; i < ring.length - 1; i++) {
      var cross = ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1];
      area += cross;
      cx += (ring[i][0] + ring[i + 1][0]) * cross;
      cy += (ring[i][1] + ring[i + 1][1]) * cross;
    }
    ring.forEach(function (v) { sx += v[0]; sy += v[1]; });
    area /= 2;
    if (Math.abs(area) < 1e-12) return [sx / ring.length, sy / ring.length];
    return [cx / (6 * area), cy / (6 * area)];
  }

  /* The name to put in a map key: the formation first, then its own code,
   * then the USGS code the polygon was actually drawn from. The last is not
   * decoration - a 1:600,000 name sitting on a 1:5,000,000 line invites the
   * reader to trust the line at 1:600,000. Matches Lithology.legend_label.
   *
   * `district` is where the polygon is, which the caller works out; the
   * site's own district is only the fallback for a polygon that could not
   * be placed. */
  function unitLabel(props, spec, district) {
    var source = String(props.unit || 'unclassified');
    if (!spec || !spec.nameLithology) return source;
    /* A class the crosswalk has nothing to say about keeps the source's own
     * wording, and on these maps it keeps the code beside it - label_with_code
     * in the Python engine, which the unit maps that name lithology pass and
     * the aquifer map does not. Dropping the code left a key entry reading
     * "Holocene" where the Python one reads "Holocene (Qe)", with nothing on
     * the figure tying the colour back to the layer it was drawn from. */
    var fallback = props.glg ? source + ' (' + props.glg + ')' : source;
    var rock = lithologyFor(props.glg,
      district === undefined ? spec.district : district);
    if (!rock || !rock.formation_name) return fallback;
    var codes = [];
    if (rock.formation_code) codes.push(rock.formation_code.replace(/;/g, ', '));
    if (props.glg) codes.push('USGS ' + props.glg);
    return rock.formation_name +
      (codes.length ? ' (' + codes.join('; ') + ')' : '');
  }

  /* One line a figure carries about a class whose source age is wrong. The
   * age is not quietly rewritten: both are shown and the note says which is
   * which, because correcting somebody else's dataset in silence leaves a
   * reader unable to tell what they are looking at. */
  function lithologyNote(props, spec, district) {
    if (!spec || !spec.nameLithology) return '';
    var rock = lithologyFor(props.glg,
      district === undefined ? spec.district : district);
    if (!rock || String(rock.usgs_era_wrong).toLowerCase() !== 'yes') return '';
    return 'The source layer dates this polygon as ' + props.unit + '; it is ' +
      'the ' + rock.formation_name + ', ' + rock.era_actual + '. The boundary ' +
      'is the 1:5,000,000 one either way.';
  }

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

  /* Every exterior ring of a Polygon or MultiPolygon, holes dropped. Used
   * where only the outline matters and a hole cannot change the answer. */
  function ringsOf(geometry) {
    if (!geometry) return [];
    if (geometry.type === 'Polygon') return geometry.coordinates.slice(0, 1);
    if (geometry.type === 'MultiPolygon') {
      return geometry.coordinates.map(function (poly) { return poly[0]; });
    }
    return [];
  }

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

  /* Does this polygon cover any ground inside the country outline?
   *
   * The bundled layers are clipped to a rectangle, not to the border, so
   * they carry polygons lying wholly in Guinea or Liberia - the Ordovician
   * and Silurian of the Bove Basin are entirely across the northern border.
   * Listing them in the key sends a reader hunting the map for a colour
   * that is not on it. Cheap and symmetric, the same test the Python engine
   * uses in mapping/regional.py as _ring_meets_country: a unit vertex
   * inside the country, or a border vertex inside the unit. */
  function meetsOutline(geometry, outline) {
    if (!outline || !outline.length) return true;
    var rings = ringsOf(geometry);
    for (var o = 0; o < outline.length; o++) {
      var border = ringsOf(outline[o].geometry);
      for (var b = 0; b < border.length; b++) {
        for (var i = 0; i < rings.length; i++) {
          for (var j = 0; j < rings[i].length; j++) {
            if (pointInRing(rings[i][j][0], rings[i][j][1], border[b])) return true;
          }
        }
        for (var k = 0; k < border[b].length; k++) {
          if (pointInFeature(border[b][k][0], border[b][k][1], geometry)) return true;
        }
      }
    }
    return false;
  }

  function onLand(lon, lat, outline) {
    if (!outline || !outline.length) return true;
    for (var i = 0; i < outline.length; i++) {
      if (pointInFeature(lon, lat, outline[i].geometry)) return true;
    }
    return false;
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

  /* Does this polygon actually reach into the window?
   *
   * The same three tests as _ring_in_box in the Python engine, and for the
   * same reason: two rectangles can overlap while the shapes inside them do
   * not touch, and a key built on the bounding boxes alone named a
   * consolidated sedimentary aquifer on a map of the Freetown peninsula
   * because that unit's box reaches across a country the polygon does not.
   * So: a vertex inside the window, a window corner inside the ring, or an
   * edge of one crossing an edge of the other. Those three are the whole of
   * it. The first is answered by the same pass that measures the ring, and
   * the extents reject the rest of the layer before the expensive tests run:
   * a national geology layer is 92 polygons and the reports draw several
   * figures each. */
  function ringInBox(geometry, box) {
    return ringsOf(geometry).some(function (ring) {
      return ringReachesBox(ring, box);
    });
  }

  function ringReachesBox(ring, box) {
    var lonMin = Infinity, lonMax = -Infinity, latMin = Infinity, latMax = -Infinity;
    for (var i = 0; i < ring.length; i++) {
      if (ring[i][0] < lonMin) lonMin = ring[i][0];
      if (ring[i][0] > lonMax) lonMax = ring[i][0];
      if (ring[i][1] < latMin) latMin = ring[i][1];
      if (ring[i][1] > latMax) latMax = ring[i][1];
      if (ring[i][0] >= box[0] && ring[i][0] <= box[2] &&
          ring[i][1] >= box[1] && ring[i][1] <= box[3]) return true;
    }
    if (!(lonMax >= box[0] && lonMin <= box[2] &&
          latMax >= box[1] && latMin <= box[3])) return false;
    var corners = [[box[0], box[1]], [box[2], box[1]],
      [box[2], box[3]], [box[0], box[3]]];
    for (var c = 0; c < corners.length; c++) {
      if (pointInRing(corners[c][0], corners[c][1], ring)) return true;
    }
    return ringCrossesBoxEdge(ring, box);
  }

  /* The remaining case: a long thin polygon - a dyke, a river, a coastal
   * strip - slicing clean through the window without a vertex landing in it
   * and without swallowing a corner. */
  function ringCrossesBoxEdge(ring, box) {
    var sides = [
      [[box[0], box[1]], [box[2], box[1]]],
      [[box[2], box[1]], [box[2], box[3]]],
      [[box[2], box[3]], [box[0], box[3]]],
      [[box[0], box[3]], [box[0], box[1]]],
    ];
    function side(a, b, c) {
      return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
    }
    for (var i = 0; i < ring.length - 1; i++) {
      for (var s = 0; s < sides.length; s++) {
        var q1 = sides[s][0], q2 = sides[s][1];
        var d1 = side(q1, q2, ring[i]), d2 = side(q1, q2, ring[i + 1]);
        var d3 = side(ring[i], ring[i + 1], q1);
        var d4 = side(ring[i], ring[i + 1], q2);
        if (d1 * d2 < 0 && d3 * d4 < 0) return true;
      }
    }
    return false;
  }

  /* Shoelace area, unsigned: which part of a chiefdom is the one worth
   * writing the name on when several are in view. */
  function ringArea(ring) {
    var sum = 0;
    for (var i = 0; i < ring.length - 1; i++) {
      sum += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1];
    }
    return Math.abs(sum / 2);
  }

  /* Where to write an area's name, given only the parts of it in view.
   *
   * The centroid of the largest ring is the right answer for a whole country
   * and the wrong one for a chiefdom clipped by the window: it lands outside
   * the frame, and the name is either not drawn or drawn on the edge
   * pointing at nothing. The mean of the vertices that are actually inside
   * the window is inside the window by construction. _label_spot in the
   * Python engine. */
  function labelSpot(rings, box) {
    var lon = 0, lat = 0, n = 0;
    rings.forEach(function (ring) {
      ring.forEach(function (v) {
        if (v[0] > box[0] && v[0] < box[2] && v[1] > box[1] && v[1] < box[3]) {
          lon += v[0]; lat += v[1]; n += 1;
        }
      });
    });
    return n < 3 ? null : [lon / n, lat / n];
  }

  /* ------------------------------------------------------------- furniture */

  /* Coarsest first, the ladder _nice_interval walks in the Python engine. */
  var GRATICULE_STEPS = [5, 2, 1, 0.5, 0.25, 0.2, 0.1, 0.05, 0.025, 0.02,
    0.01, 0.005, 0.002, 0.001];

  /* A round graticule interval giving three to six lines across.
   *
   * Five was the target and the steps were coarse, so a 1.2 degree window
   * fell to a 0.1 degree step and thirteen labels ran into each other along
   * the bottom edge. A degree label is about a tenth of the frame wide at
   * this size; six across is the most that stay apart. */
  function graticuleStep(span) {
    var target = span / 3.5;
    for (var i = 0; i < GRATICULE_STEPS.length; i++) {
      if (GRATICULE_STEPS[i] <= target) return GRATICULE_STEPS[i];
    }
    return GRATICULE_STEPS[GRATICULE_STEPS.length - 1];
  }

  /* The ticks of one axis: every round multiple of the step that falls
   * inside the frame, and nothing beyond it. A tick placed past the limit
   * made the Python engine grow its axes to include it, which put a white
   * strip on the national maps and moved every local window off its site;
   * here the frame cannot grow, so the tick would simply be drawn outside
   * the neatline, over the labels of the other axis. */
  function graticuleTicks(lo, hi, step) {
    var eps = step * 1e-6;
    var ticks = [];
    for (var v = Math.ceil(lo / step) * step; v <= hi + step / 2; v += step) {
      if (v >= lo - eps && v <= hi + eps) ticks.push(v);
    }
    return ticks;
  }

  /* A coordinate as degrees and minutes, the way a map writes them.
   *
   * -13.5 is how a spreadsheet writes a longitude. A map writes 13 degrees
   * 30 minutes West, and a hydrogeologist reading a GPS in the field is
   * reading degrees and minutes. Written as a decimal to one place the ticks
   * of a 0.05 degree graticule came out as "13.3°W" twice running, two lines
   * three minutes apart carrying the same label. _dms in the Python engine. */
  function degreeLabel(value, axis) {
    var hemi = axis === 'lat' ? (value < 0 ? 'S' : 'N') : (value < 0 ? 'W' : 'E');
    var v = Math.abs(value);
    var deg = Math.floor(v);
    var minutes = (v - deg) * 60;
    /* 12.99999 is sixty minutes past twelve, which is thirteen degrees, not
     * "12°60'". Floating point put a tick just short of 13 W and the
     * graticule on every map of the Western Area was labelled 12°60'W. */
    if (minutes >= 59.95) { deg += 1; minutes = 0; }
    if (minutes < 0.05) return deg + '°' + hemi;
    var whole = C.pyRound(minutes, 0);
    if (Math.abs(minutes - whole) < 0.05) {
      return deg + '°' + (whole < 10 ? '0' + whole : String(whole)) + '′' + hemi;
    }
    var text = C.pyFixed(minutes, 1);
    return deg + '°' + (text.length < 4 ? '0' + text : text) + '′' + hemi;
  }

  var SCALE_STEPS_KM = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000];

  function drawMapFurniture(svg, project, rect, p, options) {
    var opts = options || {};
    var b = project.bounds;

    /* graticule, labelled where it meets the neatline. The ticks are spaced
     * across the frame rather than across the data: the projection
     * letterboxes the extent, so a window is drawn with a margin of real
     * ground either side of it, and ticks laid out over the extent alone
     * stopped short of the neatline with map still to go. */
    if (opts.graticule !== false) {
      var g = svgEl('g', { 'aria-hidden': 'true' });
      var frame = project.visibleBox();
      /* One interval for both axes, taken from the wider span of the extent
       * the map was asked for: carto.graticule calls _nice_interval on
       * max(x1 - x0, y1 - y0) of its axis limits and rules both axes with
       * the answer. A step worked out per axis from the letterboxed frame
       * instead ruled the two edges differently - a 4.5 km window came out
       * with a 1.2 minute graticule along the bottom and a 1.5 minute one up
       * the side - and, because the frame is the wider of the two, it also
       * stepped a 48 km window at 15 minutes where the Python one steps 12.
       * The ticks are still laid across the frame rather than the extent,
       * because the projection letterboxes the window and ticks spaced over
       * the extent alone stopped short of the neatline with map still to go. */
      var step = graticuleStep(Math.max(b.lonMax - b.lonMin, b.latMax - b.latMin));
      graticuleTicks(frame[0], frame[2], step).forEach(function (lon) {
        var x = project(lon, b.latMax)[0];
        /* clamped to the frame, and no label where its text would run off
         * the neatline: a name half outside the frame points at nothing */
        if (x < rect.x || x > rect.x + rect.w) return;
        if (x < rect.x + 14 || x > rect.x + rect.w - 14) return;
        g.appendChild(svgEl('line', {
          x1: x, y1: rect.y, x2: x, y2: rect.y + rect.h,
          stroke: p.grid, 'stroke-width': 0.7, 'stroke-dasharray': '2 4',
        }));
        g.appendChild(svgEl('text', {
          x: x, y: rect.y + rect.h + 11, 'text-anchor': 'middle',
          'font-size': 8.5, fill: p.muted, text: degreeLabel(lon, 'lon'),
        }));
      });
      graticuleTicks(frame[1], frame[3], step).forEach(function (lat) {
        var y = project(b.lonMin, lat)[1];
        if (y < rect.y || y > rect.y + rect.h) return;
        if (y < rect.y + 12 || y > rect.y + rect.h - 12) return;
        g.appendChild(svgEl('line', {
          x1: rect.x, y1: y, x2: rect.x + rect.w, y2: y,
          stroke: p.grid, 'stroke-width': 0.7, 'stroke-dasharray': '2 4',
        }));
        g.appendChild(svgEl('text', {
          x: rect.x - 4, y: y + 3, 'text-anchor': 'end',
          'font-size': 8.5, fill: p.muted, text: degreeLabel(lat, 'lat'),
        }));
      });
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

  /* ------------------------------------------- sea, and the land beyond it */

  /* The land across the border that a window can see.
   *
   * The toolkit bundles no outline of Guinea or Liberia; the USGS layer
   * covers the whole clip window and has no polygon over the sea, so its
   * units are what tells land across the border from the Atlantic. The
   * Python engine takes the same rings in foreign_land_rings(). */
  function foreignLandFeatures(box) {
    var layer = ((GWT.data || {}).geo || {}).geology || {};
    var features = layer.features || [];
    if (!box) return features;
    return features.filter(function (feature) {
      return ringInBox(feature.geometry, box);
    });
  }

  /* Fill the frame as sea, then lay the country on top of it.
   *
   * Sierra Leone has 400 km of coast and this toolkit's busiest site is on
   * the Freetown peninsula, where half of every window is Atlantic. Drawn as
   * the page it read as blank paper, so the coastline looked like the edge
   * of the data rather than the edge of the land.
   *
   * Everything outside the national outline is filled, and across the land
   * border that is Guinea or Liberia, not ocean: those are painted in the
   * paper tone between the two, which is what sea_and_neighbours does in the
   * Python engine. The land across the border is passed in by the caller,
   * which knows what it is; without it everything outside the outline stays
   * sea. The country's own ground is painted over them again, so a foreign
   * polygon reaching across the border cannot tint the inside. */
  function seaAndNeighbours(canvas, outline, background, foreign) {
    if (!outline || !outline.length) return;
    canvas.layer.appendChild(svgEl('rect', {
      x: canvas.rect.x, y: canvas.rect.y,
      width: canvas.rect.w, height: canvas.rect.h, fill: MAP_SEA,
    }));
    (foreign || []).forEach(function (feature) {
      canvas.layer.appendChild(svgEl('path', {
        d: geometryPath(feature.geometry, canvas.project),
        fill: MAP_FOREIGN_LAND, stroke: 'none',
      }));
    });
    outline.forEach(function (feature) {
      canvas.layer.appendChild(svgEl('path', {
        d: geometryPath(feature.geometry, canvas.project),
        fill: background, stroke: 'none',
      }));
    });
  }

  /* One counter for every clip path this file mints, because an id that
   * repeats on a page silently makes two figures share one shape. */
  var clipSeq = 0;

  /* Everything beyond the national boundary, painted out as sea, with the
   * land across the border put back on top of it.
   *
   * The unit layers are clipped to a rectangle, not to the border, so a
   * polygon that straddles it runs on across Guinea and across the Atlantic;
   * this is what stops it, and it is the reason the key can promise that
   * every colour in it is findable inside the country. A rectangle with the
   * country rings punched out of it, even-odd filled - the compound path
   * _mask_outside_country builds in the Python engine - then the foreign
   * polygons clipped to that same shape, so nothing lands inside. */
  function maskOutsideCountry(canvas, outline, box) {
    if (!outline || !outline.length) return;
    var r = canvas.rect;
    var d = 'M' + r.x + ' ' + r.y + 'L' + (r.x + r.w) + ' ' + r.y +
      'L' + (r.x + r.w) + ' ' + (r.y + r.h) + 'L' + r.x + ' ' + (r.y + r.h) + 'Z';
    outline.forEach(function (feature) {
      d += ' ' + geometryPath(feature.geometry, canvas.project);
    });
    clipSeq += 1;
    var maskId = 'gwt-sea-' + clipSeq;
    var defs = svgEl('defs');
    defs.appendChild(svgEl('clipPath', { id: maskId }, [svgEl('path', {
      d: d, 'clip-rule': 'evenodd',
    })]));
    canvas.svg.insertBefore(defs, canvas.svg.firstChild);
    canvas.layer.appendChild(svgEl('path', {
      d: d, 'fill-rule': 'evenodd', fill: MAP_SEA, stroke: 'none',
    }));
    var neighbours = svgEl('g', { 'clip-path': 'url(#' + maskId + ')' });
    foreignLandFeatures(box).forEach(function (feature) {
      neighbours.appendChild(svgEl('path', {
        d: geometryPath(feature.geometry, canvas.project),
        fill: MAP_FOREIGN_LAND, stroke: 'none',
      }));
    });
    canvas.layer.appendChild(neighbours);
  }

  /* Everything the caller draws into the layer is held inside the neatline.
   * A chiefdom boundary or a geological contact that leaves the window runs
   * on over the title and the key otherwise, and the frame stops meaning
   * anything. */
  function clipToFrame(canvas) {
    clipSeq += 1;
    var clipId = 'gwt-clip-' + clipSeq;
    var defs = svgEl('defs');
    defs.appendChild(svgEl('clipPath', { id: clipId }, [svgEl('rect', {
      x: canvas.rect.x, y: canvas.rect.y,
      width: canvas.rect.w, height: canvas.rect.h,
    })]));
    canvas.svg.insertBefore(defs, canvas.svg.firstChild);
    canvas.layer.setAttribute('clip-path', 'url(#' + clipId + ')');
  }

  /* --------------------------------------------------------- place names */

  /* Where each corner's furniture sits, in fractions of the frame measured
   * from its lower left, as _INSET_BOXES in the Python engine. One table, so
   * the plate that is drawn and the box the names are kept out of are the
   * same rectangle. */
  var INSET_BOXES = {
    'lower right': [0.695, 0.02, 0.29, 0.34],
    'upper left': [0.015, 0.63, 0.29, 0.34],
    'lower left': [0.015, 0.02, 0.29, 0.34],
    'upper right': [0.695, 0.63, 0.29, 0.34],
  };

  /* The same rectangle in pixels. SVG counts y downwards and the table
   * upwards, so the top edge is what is left above the box. */
  function insetRect(rect, corner) {
    var f = INSET_BOXES[corner] || INSET_BOXES['lower right'];
    return {
      x: rect.x + rect.w * f[0], y: rect.y + rect.h * (1 - f[1] - f[3]),
      w: rect.w * f[2], h: rect.h * f[3],
    };
  }

  /* And the same plate in lon/lat, for the label placement, which works in
   * map units. Read back through the projection rather than worked out from
   * the window: the frame is letterboxed around the window, so the corner of
   * one is not the corner of the other, and a name is only safe if the box
   * it is kept out of is the rectangle the plate really covers. */
  function furnitureBox(canvas, corner) {
    var r = insetRect(canvas.rect, corner);
    var sw = canvas.project.invert(r.x, r.y + r.h);
    var ne = canvas.project.invert(r.x + r.w, r.y);
    return [sw[0], sw[1], ne[0], ne[1]];
  }

  function insideBox(lon, lat, box) {
    return box[0] <= lon && lon <= box[2] && box[1] <= lat && lat <= box[3];
  }

  /* Keep the labels that fit, drop the ones that would overlap.
   *
   * A name nobody can read is worse than no name: the reader cannot tell
   * which polygon the legible one belongs to either. Greedy, largest-first,
   * over estimated text boxes rather than points - testing centre-to-centre
   * distance kept "Western Area Urban" and "Western Area Rural" because
   * their centroids are far enough apart, while the words themselves,
   * fifteen characters wide, ran straight through each other. `priority`
   * (bigger wins a collision, the polygon's area is the obvious choice)
   * keeps the name of the chiefdom filling the frame and drops the sliver
   * clipped by the corner. `reserved` are boxes nothing may be written
   * over: the locator inset, the key. carto.declutter in the Python engine,
   * with the same estimates, so the two engines print the same names. */
  function declutter(candidates, extent, minSepFrac, priority, reserved) {
    if (!candidates.length) return [];
    var sep = minSepFrac || 0.052;
    var width = extent[2] - extent[0], height = extent[3] - extent[1];
    var charW = width * sep * 0.30, lineH = height * sep * 0.62;
    var order = candidates.map(function (c, i) { return i; });
    if (priority) {
      order.sort(function (a, b) { return priority[b] - priority[a]; });
    }
    var kept = [], boxes = (reserved || []).slice();
    order.forEach(function (i) {
      var lon = candidates[i][0], lat = candidates[i][1], text = candidates[i][2];
      var halfW = text.length * charW / 2, halfH = lineH / 2;
      var box = [lon - halfW, lat - halfH, lon + halfW, lat + halfH];
      /* a name whose word runs off the frame, sideways or vertically,
       * points at nothing */
      if (!(extent[0] < lon && lon < extent[2] &&
            extent[1] < lat && lat < extent[3])) return;
      if (box[0] < extent[0] || box[2] > extent[2]) return;
      if (box[1] < extent[1] || box[3] > extent[3]) return;
      var clash = boxes.some(function (b) {
        return box[0] < b[2] && box[2] > b[0] && box[1] < b[3] && box[3] > b[1];
      });
      if (clash) return;
      kept.push(candidates[i]);
      boxes.push(box);
    });
    return kept;
  }

  /* A place name with a cut-out behind it, so it reads over any fill.
   * Without the halo the name takes the colour of whatever it landed on and
   * a third of the labels become unreadable. */
  function placeMapLabel(svg, x, y, text, p, options) {
    var opts = options || {};
    svg.appendChild(svgEl('text', {
      x: x, y: y, 'text-anchor': 'middle', 'font-size': opts.size || 8,
      'font-style': opts.style || 'italic', fill: opts.fill || p.muted,
      stroke: p.surface, 'stroke-width': 2.6, 'paint-order': 'stroke',
      text: text,
    }));
  }

  /* -------------------------------------------------------- scale caveat */

  /* Both bundled layers are published at 1:5,000,000. */
  var USGS_SOURCE_SCALE = 5000000;
  var BGS_SOURCE_SCALE = 5000000;

  /* The BGS Africa Groundwater Atlas user guide (OR/21/063, section 2.2) on
   * what its country maps are for. Quoted rather than paraphrased: it is the
   * publisher's own limit on its own data, and it is more use to a reader
   * deciding what to trust than any sentence this toolkit could write. */
  var BGS_PUBLISHER_NOTE = 'Its publisher states these maps are "not ' +
    'suitable for providing detailed information on geology and ' +
    'hydrogeology at a sub-national (e.g. catchment) scale".';

  /* The note a small window over a small-scale dataset has earned: the
   * engine's C.scaleCaveat, _scale_caveat in the Python engine word for word,
   * where the parity suite can hold the sentence to it. */
  var scaleCaveat = C.scaleCaveat;

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

  /* `spec.classes` is a fixed scale: [{kind, max_people_per_point, label,
   * colour}], the table the Python engine reads too. Without one the classes
   * were five quantiles recomputed from whatever was on this map, so the same
   * chiefdom changed colour between the district view and the chiefdom view
   * and neither key said what a colour meant. A map that cannot be compared
   * with another map of the same country is not much of a map. */
  function choropleth(spec) {
    var features = spec.features || [];
    var fixed = spec.classes && spec.classes.length ? spec.classes : null;
    var values = features.map(spec.value).filter(function (v) {
      return typeof v === 'number' && isFinite(v);
    });
    var breaks = spec.breaks || (fixed ? fixedBreaks(fixed)
      : quantileBreaks(values, 5));
    var pal = palette();
    /* One colour per class, sampled across the whole ramp. Slicing a fixed
     * window off it gave fewer colours than classes as soon as the breaks
     * were supplied rather than computed, and the top classes then shared a
     * colour while the legend still listed them apart. */
    var classes = breaks.length + 1;
    var ramp = [];
    if (fixed) {
      ramp = fixed.filter(function (c) { return c.kind === 'class'; })
        .map(function (c) { return c.colour; });
    } else {
      for (var c = 0; c < classes; c++) {
        var t = classes === 1 ? 0.5 : c / (classes - 1);
        ramp.push(pal.seq[Math.round(t * (pal.seq.length - 1))]);
      }
    }
    var noSource = fixed ? classColour(fixed, 'no_source') : '#D8D4CB';
    var noData = fixed ? classColour(fixed, 'no_data') : '#D8D4CB';

    var legendItems = [];
    if (spec.legend !== false && breaks.length) {
      ramp.forEach(function (colour, i) {
        var band = fixed ? fixed.filter(function (c) {
          return c.kind === 'class';
        })[i] : null;
        var lo = i === 0 ? null : breaks[i - 1];
        var hi = i < breaks.length ? breaks[i] : null;
        legendItems.push({
          colour: colour,
          label: band ? band.label
            : (lo === null ? 'under ' + S.sig(hi, 3)
              : (hi === null ? S.sig(lo, 3) + ' and over'
                : S.sig(lo, 3) + ' to ' + S.sig(hi, 3))),
        });
      });
      /* An area with no functional source at all is the worst case, not a
       * missing one - it ranks first by definition. Both were the same grey,
       * so the areas most in need looked exactly like the areas nothing is
       * known about. */
      if (fixed && features.some(function (f) { return isNoSource(spec.value(f)); })) {
        legendItems.push({ colour: noSource, label: classLabel(fixed, 'no_source') });
      }
      if (features.some(function (f) { return isNoData(spec.value(f)); })) {
        legendItems.push({
          colour: noData,
          label: fixed ? classLabel(fixed, 'no_data') : 'no figure recorded',
        });
      }
    }

    var canvas = mapCanvas(spec, legendItems, features);
    /* plot_coverage_choropleth paints sea and neighbouring land before the
     * areas (regional.py:1170), as the portfolio map does. The browser's
     * coverage map drew the country on blank paper, so the Atlantic and a
     * country with no figures looked the same. */
    clipToFrame(canvas);
    seaAndNeighbours(canvas, spec.outline || [], MAP_LAND,
      foreignLandFeatures(canvas.project.visibleBox()));
    features.forEach(function (feature) {
      var v = spec.value(feature);
      var cls = classify(v, breaks);
      var fill;
      if (isNoData(v)) fill = noData;
      else if (isNoSource(v)) fill = noSource;
      else fill = ramp[Math.min(cls, ramp.length - 1)];
      canvas.layer.appendChild(svgEl('path', {
        d: geometryPath(feature.geometry, canvas.project),
        'fill-rule': 'evenodd',
        fill: fill,
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

  /* The two out-of-ramp cases, told apart the same way the Python engine tells
   * them apart: nothing known at all, versus a mapped area with no working
   * source in it. */
  function isNoData(v) {
    return v === null || v === undefined || typeof v !== 'number' || isNaN(v);
  }

  function isNoSource(v) {
    return typeof v === 'number' && !isNaN(v) && !isFinite(v);
  }

  function classColour(classes, kind) {
    var hit = classes.filter(function (c) { return c.kind === kind; })[0];
    return hit ? hit.colour : '#D8D4CB';
  }

  function classLabel(classes, kind) {
    var hit = classes.filter(function (c) { return c.kind === kind; })[0];
    return hit ? hit.label : kind;
  }

  function fixedBreaks(classes) {
    return classes.filter(function (c) {
      return c.kind === 'class' && c.max_people_per_point !== '' &&
        c.max_people_per_point !== null && c.max_people_per_point !== undefined;
    }).map(function (c) { return Number(c.max_people_per_point); });
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

  /* The districts whose ground the Rokel River Group belt runs under, as
   * the crosswalk's regions name them. The Python engine tests
   * region_of(district) against the same two. */
  var ROKEL_BELT_REGIONS = ['coastal plain', 'north and centre'];

  /* The extent a whole-country map covers: the national outline's own bounds
   * with the margin the Python engine puts round them, 0.15 degrees east and
   * west and 0.12 north and south. Null when no outline was supplied. */
  function countryBox(outline) {
    if (!outline || !outline.length) return null;
    var b = featureBounds(outline);
    if (!isFinite(b.lonMin)) return null;
    return [b.lonMin - 0.15, b.latMin - 0.12, b.lonMax + 0.15, b.latMax + 0.12];
  }

  /* Is there ground in the window that the source layer draws no polygon
   * for?
   *
   * The bundled layers stop short of the coast in places - the Bullom shore
   * and the Sherbro estuaries most of all - and that ground is painted the
   * not-mapped tint. Only when it is actually on screen, though: a window
   * over the interior has no gaps in it, and a key entry for something not
   * on the map is its own small lie. The same 56 by 56 grid as
   * _unmapped_land_in_view in the Python engine, so the two engines agree
   * on whether the entry has been earned. */
  function unmappedLandInWindow(outline, units, box, samples) {
    if (!outline || !outline.length) return false;
    var n = samples || 56;
    for (var i = 0; i < n; i++) {
      var lon = box[0] + (box[2] - box[0]) * i / (n - 1);
      for (var j = 0; j < n; j++) {
        var lat = box[1] + (box[3] - box[1]) * j / (n - 1);
        if (!onLand(lon, lat, outline)) continue;
        var covered = units.some(function (unit) {
          return pointInFeature(lon, lat, unit.geometry);
        });
        if (!covered) return true;
      }
    }
    return false;
  }

  /* A categorical polygon layer - geology or aquifer productivity - clipped
   * to a window around the site when there is one.
   *
   * The layers carry their own published colours, so the map reads the same
   * way the source sheet does rather than being recoloured here.
   *
   * The legend names the units that cover ground inside the window that was
   * drawn, by the same three tests the Python engine uses in _ring_in_box.
   * Selecting by bounding box, which is the cheap first pass, would put a
   * unit in the legend whose only claim on the window is that its box
   * reaches across a country its polygon does not. */
  function thematicMap(spec) {
    var key = spec.key || 'unit';
    var window_ = spec.window || null;
    var outline = spec.outline || [];
    /* Units wholly outside Sierra Leone are dropped before anything else:
     * they are masked away when the map is drawn, so a key entry for one
     * is a colour the reader cannot find. */
    var all = (spec.features || []).filter(function (feature) {
      return meetsOutline(feature.geometry, outline);
    });
    if (!all.length) all = spec.features || [];

    var features = all, clip = null;
    if (window_) {
      var dLat = window_.radiusKm / 111.320;
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

    /* The window itself sets the extent, so a 40 km map is a 40 km map even
     * when the polygon covering it runs the length of the country. With no
     * window, the country sets it: _plot_units_map frames on the outline's
     * own bounds with a fixed margin (regional.py:735-737), where taking the
     * extent from the unit polygons framed the national maps on ground that
     * runs into Guinea and Liberia and drew them at a wider scale than the
     * Python ones, down to ruling the graticule a step coarser. */
    var nationalBox = clip ? null : countryBox(outline);
    var boxExtent = function (bx) {
      return [{ geometry: { type: 'Polygon', coordinates: [[
        [bx[0], bx[1]], [bx[2], bx[1]], [bx[2], bx[3]], [bx[0], bx[3]],
      ]] } }];
    };
    var extent = clip ? boxExtent(clip)
      : (nationalBox ? boxExtent(nationalBox) : features);

    /* Which units are really in the window, and where each of them is.
     *
     * The key is scoped to the window that was drawn - the box the title and
     * the scale caveat describe - and not to the whole frame: the projection
     * letterboxes the window, so the frame shows a few kilometres of ground
     * beyond it either side, and a unit that reaches no further than that
     * margin is a colour the reader is sent hunting the map for. The Python
     * engine keys on the same box, its axes being the window exactly.
     *
     * Each polygon carries the district it is in rather than the site's,
     * because the crosswalk that names the rock is a regional table: scoped
     * by the site, the same Freetown Complex polygon came out as the
     * Freetown Layered Complex on one map and as "Paleozoic Igneous", the
     * age the crosswalk itself calls wrong, on another 100 km away. */
    var inWindow = (clip ? features.filter(function (feature) {
      return ringInBox(feature.geometry, clip);
    }) : features).map(function (feature) {
      return {
        feature: feature,
        district: unitDistrict(feature.geometry) || spec.district,
      };
    });

    /* Is any of the ground in the key's box unmapped? Settled here rather
     * than inside legendFor because the entry has a note to go with it, and
     * the note has to be written before mapCanvas measures the credit
     * block. Without a window the box is the national extent the Python
     * engine's axes carry - the country's own bounds with its margin round
     * them - because the frame is not laid out yet. */
    var keyBox = clip || countryBox(outline);
    var gapInView = !!keyBox && unmappedLandInWindow(
      outline, inWindow.map(function (placed) { return placed.feature; }),
      keyBox);

    function legendFor() {
      var seen = [];
      inWindow.forEach(function (placed) {
        var props = placed.feature.properties || {};
        var label = spec.nameLithology
          ? unitLabel(props, spec, placed.district)
          : String(props[key] || 'unclassified');
        if (!seen.some(function (s) { return s.label === label; })) {
          seen.push({ label: label, colour: unitColour(props, spec),
            era: eraRank(props), code: unitCode(props) });
        }
      });
      /* Era first and the source's own code after it, which is how the
       * Python engine orders a key: youngest at the top, the basement under
       * it, the non-geological classes last. The code is compared as Python
       * compares strings, by code point, rather than by the locale's
       * collation. */
      seen.sort(function (a, b) {
        if (a.era !== b.era) return a.era - b.era;
        return a.code < b.code ? -1 : (a.code > b.code ? 1 : 0);
      });
      var items = seen.slice();
      /* ground the source draws nothing for, named in the key rather than
       * left as an unexplained tint: beige with nothing beside it leaves a
       * reader guessing whether it is sea, a gap, or a unit whose colour
       * they have misread */
      if (gapInView) {
        items.push({ label: 'Not mapped at this scale',
          colour: MAP_NOT_MAPPED });
      }
      (spec.points || []).forEach(function (point) {
        if (!point.label) return;
        items.push({
          label: point.legend || point.label, kind: point.kind || 'diamond',
          colour: point.colour || palette().secondary,
        });
      });
      return items;
    }

    /* An age the source has wrong is said out loud rather than silently
     * corrected, so it has to be in the credit block before mapCanvas
     * measures it. Driven by the polygons the key will name, so a window
     * that does not reach the Freetown peninsula carries no note about it. */
    var notes = [];
    inWindow.forEach(function (placed) {
      var n = lithologyNote(placed.feature.properties || {}, spec, placed.district);
      if (n && notes.indexOf(n) < 0) notes.push(n);
    });
    /* the gap entry says what the tint is; this says why there is one, so a
     * reader is not left deciding for themselves whether the beige is sea,
     * a hole in the data, or a colour they have misread */
    if (gapInView) {
      notes.push('The not-mapped tint is land inside Sierra Leone that the ' +
        'source layer draws no polygon for; at this scale its coastal units ' +
        'stop short of the shore.');
    }
    /* The Rokel River Group belt sits inside the USGS Precambrian polygon,
     * which the 1:5,000,000 map does not separate from the granite around
     * it. The aquifer map beside this one shows the belt as fracture flow in
     * indurated sediments, and a reader comparing the two figures was given
     * nothing to reconcile them with. */
    if (spec.nameLithology &&
        ROKEL_BELT_REGIONS.indexOf(regionOf(spec.district)) >= 0 &&
        inWindow.some(function (placed) {
          return (placed.feature.properties || {}).glg === 'pCm';
        })) {
      notes.push('The Precambrian polygon here spans both the Leonean ' +
        'granite-gneiss and the Rokel River Group belt (Port Loko, Kambia, ' +
        'Moyamba, Tonkolili), which the 1:5,000,000 map does not separate; ' +
        'the aquifer map shows the belt as fracture flow in indurated ' +
        'sediments.');
    }
    /* the window that was drawn, not the one that was asked for: without a
     * position there is no window and the national map is the scale the
     * data was published at, which needs no apology */
    var caveat = scaleCaveat(window_ ? window_.radiusKm : null,
      spec.sourceScale, spec.publisherNote);
    if (caveat) notes.push(caveat);
    var credited = Object.assign({}, spec);
    if (notes.length) {
      credited.credit = [spec.credit, notes.join('  ')].filter(Boolean).join('  ');
    }

    var canvas = mapCanvas(credited, legendFor, extent);
    var p = canvas.palette;

    clipToFrame(canvas);

    /* Sea first, then the country, then the units on top of it. What is
     * left showing in the land tint is ground the source layer draws
     * nothing for, and the key names it. */
    seaAndNeighbours(canvas, outline, MAP_NOT_MAPPED);

    features.forEach(function (feature) {
      var props = feature.properties || {};
      canvas.layer.appendChild(svgEl('path', {
        d: geometryPath(feature.geometry, canvas.project),
        /* A hole is ground the unit does not cover - a dyke cutting the
         * country rock, a window of something else. evenodd leaves it open
         * whichever way the interior ring winds. */
        'fill-rule': 'evenodd',
        fill: unitColour(props, spec), 'fill-opacity': 0.85,
        stroke: p.surface, 'stroke-width': 0.5,
      }, [svgEl('title', { text: String(props[key] || 'unclassified') })]));
    });
    /* and the units stop at the border: what runs on past it is sea, or
     * Guinea and Liberia in the paper tone */
    maskOutsideCountry(canvas, outline, clip || canvas.project.visibleBox());
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
    clipToFrame(canvas);
    /* A location map of a coastal district is half Atlantic and the rest of
     * the frame is Guinea; drawn as the page, both read as blank paper and
     * the coastline looked like the edge of the data. The national outline
     * is taken from the context layer when the caller has not named it,
     * because that is how the boundary layers arrive. */
    var outline = spec.outline || context.filter(function (feature) {
      return (feature.properties || {}).level === 'ADM0';
    });
    seaAndNeighbours(canvas, outline, MAP_LAND,
      foreignLandFeatures(canvas.project.visibleBox()));
    context.forEach(function (feature) {
      canvas.layer.appendChild(svgEl('path', {
        d: geometryPath(feature.geometry, canvas.project),
        'fill-rule': 'evenodd',
        fill: spec.contextFill ? spec.contextFill(feature) : '#EDEAE3',
        stroke: p.axis, 'stroke-width': 0.7,
      }, [svgEl('title', {
        text: String((feature.properties || {}).name ||
          (feature.properties || {}).shapeName || ''),
      })]));
    });
    /* Karene and Falaba have no polygon of their own in the boundary layer,
     * which predates them, so a locator for either lights the chiefdoms the
     * crosswalk assigns to it, over the district they were split from, as
     * plot_admin_map does. Lit by name alone, the district was never lit and
     * the legend named it in a colour that was nowhere on the map. */
    var highlight = spec.highlight || [];
    highlight.forEach(function (feature) {
      canvas.layer.appendChild(svgEl('path', {
        d: geometryPath(feature.geometry, canvas.project),
        'fill-rule': 'evenodd', fill: spec.highlightFill || '#CFE0D6',
        stroke: '#7E93A6', 'stroke-width': 0.5,
      }));
    });
    /* The districts were drawn as shapes with a hover title and nothing
     * written on them, so a printed location map named no district at all.
     * The same declutter the study-area map uses keeps a name off its
     * neighbours and off the frame. */
    if (spec.labelContext) {
      var nameBox = canvas.project.visibleBox();
      var nameCandidates = [];
      /* a district lit through its chiefdoms is named once, over them, and
       * first, so the declutter keeps it over the older district's name */
      if (highlight.length && spec.highlightLabel) {
        var sx = 0, sy = 0, count = 0;
        highlight.forEach(function (feature) {
          ringsOf(feature.geometry).forEach(function (ring) {
            ring.forEach(function (c) { sx += c[0]; sy += c[1]; count += 1; });
          });
        });
        if (count) nameCandidates.push([sx / count, sy / count, spec.highlightLabel]);
      }
      context.forEach(function (feature) {
        var props = feature.properties || {};
        var text = String(props.name || props.shapeName || '');
        if (!text) return;
        var rings = ringsOf(feature.geometry);
        if (!rings.length) return;
        var centre = ringCentroid(rings[0]);
        nameCandidates.push([centre[0], centre[1], text]);
      });
      declutter(nameCandidates, nameBox, 0.06).forEach(function (candidate) {
        var at = canvas.project(candidate[0], candidate[1]);
        placeMapLabel(canvas.layer, at[0], at[1], candidate[2], p,
          { size: 7.5, fill: p.muted });
      });
    }

    drawMapPoints(canvas, points.map(function (pt) {
      return Object.assign({ kind: 'diamond', size: 6.5 }, pt);
    }));
    return canvas.finish();
  }

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

  /* =================================== survey sections and subsurface maps */

  /* The browser geophysical report drew no figure the survey itself produced:
   * no geoelectric section, no layer pseudo-section and none of the four
   * subsurface maps, while the Python engine drew every one of them
   * (ROADMAP webapp-parity-5). A client reading the browser's report of the
   * same survey got the text of a geophysical investigation with none of its
   * pictures. The geometry, the interpolation and the refusals are mirrored in
   * gwt-core.js; these are the figures drawn from them.
   *
   * Every one of these functions returns null where the engine handed back a
   * reason instead of geometry, and the report layer prints that reason. That
   * is the point of the pairing: a section drawn between two soundings 20 km
   * apart, or a surface interpolated through two points, is worse than no
   * figure at all, because a figure is read as a measurement.
   */

  /* config.py HouseStyle.figure_width_in. The Python figures are 6.3 in wide
   * and maps.py _figsize gives every map its height from the ground it covers,
   * so the browser figure is shaped like the report's rather than being a
   * fixed rectangle the same survey is squashed into. */
  var FIGURE_WIDTH_IN = 6.3;

  /* ---------------------------------------------------------- colour ramps */

  /* matplotlib's colour ramps, as the anchors they are interpolated from.
   *
   * The Python names a colormap per figure and the browser has to arrive at
   * the same picture: a depth-to-bedrock map whose deep ground is pale beside
   * a matplotlib one whose deep ground is dark are two different findings to
   * anybody holding both reports. These are not theme colours and must not
   * come from palette() - they are the data scale itself, the thing the
   * colour bar is drawn from - which is why they are written out here the way
   * PROTECTIVE_CLASSES and GEOLOGY_COLOURS are.
   *
   * YlOrBr and GnBu are ColorBrewer's nine-colour ramps and these are their
   * exact anchors; terrain is matplotlib's own piecewise definition, kinks
   * and all; viridis is a 256-entry table sampled at seventeen points, which
   * holds it to under 5 of 255 on any channel. */
  var COLOUR_RAMPS = {
    viridis: {
      colours: ['#440154', '#48186A', '#472D7B', '#424086', '#3B528B',
        '#33638D', '#2C728E', '#26828E', '#21918C', '#1FA088', '#28AE80',
        '#3FBC73', '#5EC962', '#84D44B', '#ADDC30', '#D8E219', '#FDE725'],
    },
    YlOrBr: {
      colours: ['#FFFFE5', '#FFF7BC', '#FEE390', '#FEC34F', '#FE9829',
        '#EB6F14', '#CB4B02', '#983404', '#662506'],
    },
    GnBu: {
      colours: ['#F7FCF0', '#E0F3DB', '#CCEBC5', '#A7DDB5', '#7ACCC4',
        '#4DB2D3', '#2A8BBE', '#0867AB', '#084081'],
    },
    terrain: {
      colours: ['#333399', '#0099FF', '#00CC66', '#FFFF99', '#805C54', '#FFFFFF'],
      positions: [0, 0.15, 0.25, 0.5, 0.75, 1],
    },
    /* ColorBrewer's eleven-colour RdYlGn, which is matplotlib's own anchor
     * table for it. The suitability map is read as a traffic light - red is
     * a poor drilling target and green is a good one - so a browser ramp
     * that merely looked similar would put a peg the report calls moderate
     * in the green the reader takes for good. */
    RdYlGn: {
      colours: ['#A50026', '#D73027', '#F46D43', '#FDAE61', '#FEE08B',
        '#FFFFBF', '#D9EF8B', '#A6D96A', '#66BD63', '#1A9850', '#006837'],
    },
  };

  function hexChannels(hex) {
    var m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(String(hex || '').trim());
    if (!m) return [0, 0, 0];
    return [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)];
  }

  function mixHex(a, b, f) {
    var ca = hexChannels(a), cb = hexChannels(b), out = '#', i, v;
    for (i = 0; i < 3; i += 1) {
      v = Math.round(ca[i] + (cb[i] - ca[i]) * f);
      v = Math.max(0, Math.min(255, v));
      out += (v < 16 ? '0' : '') + v.toString(16).toUpperCase();
    }
    return out;
  }

  /* The ramp `name` at position `t`, clamped to its ends the way matplotlib
   * clamps a Normalize: a value under vmin takes the first colour on the bar
   * rather than dropping out of the figure. */
  function rampColour(name, t) {
    var ramp = COLOUR_RAMPS[name] || COLOUR_RAMPS.viridis;
    var cols = ramp.colours, n = cols.length, i;
    var x = (typeof t === 'number' && isFinite(t)) ? Math.max(0, Math.min(1, t)) : 0;
    /* matplotlib does not interpolate its ramps continuously: it builds a
     * 256-entry lookup table and picks entry min(floor(t * 256), 255), which
     * stands for position i/255. Skipping that step put the browser up to 5
     * of 255 off matplotlib on the steep leg of the terrain ramp, where a
     * bedrock elevation map changes from blue to green; mirroring it holds
     * every banded ramp here to one part in 255 of the Python's. */
    x = Math.min(Math.floor(x * 256), 255) / 255;
    var pos = ramp.positions;
    if (!pos) {
      pos = [];
      for (i = 0; i < n; i += 1) pos.push(i / (n - 1));
    }
    for (i = 0; i < n - 1; i += 1) {
      if (x <= pos[i + 1] || i === n - 2) {
        var width = pos[i + 1] - pos[i];
        return mixHex(cols[i], cols[i + 1], width > 0 ? (x - pos[i]) / width : 0);
      }
    }
    return cols[n - 1];
  }

  /* ves/plots.py _rho_norm, applied: where one layer resistivity sits on the
   * log scale spanning the decades the drawn models occupy. The Python clamps
   * at the bottom of the scale - norm(max(rho, norm.vmin)) - so a layer under
   * the scale takes the darkest colour on the bar instead of a blank column. */
  function rhoRampColour(range, rho) {
    var lo = range[0], hi = range[1];
    var span = Math.log(hi) - Math.log(lo);
    var v = Math.max(Number(rho), lo);
    return rampColour('viridis', span > 0 ? (Math.log(v) - Math.log(lo)) / span : 0);
  }

  /* The white rule matplotlib draws along a layer boundary, along a contour
   * and around a reading. It is ink on a data-coloured fill rather than ink
   * on the page, so it is not a theme token: a token that followed the theme
   * would vanish into the dark end of the viridis ramp the moment the reader
   * switched to the dark theme, which is exactly where the boundary between a
   * 4 ohm-m clay and a 9 ohm-m clay has to stay visible. */
  var ON_RAMP_INK = '#FFFFFF';

  /* ------------------------------------------------------------ colour bar */

  /* The colour bar, drawn as the thing it stands for.
   *
   * A banded fill gets a banded bar labelled at the contour levels
   * themselves, because that is what matplotlib's colorbar does for a
   * contourf and the numbers beside the browser's bar have to be the numbers
   * beside the report's. A continuous log scale gets a smooth ramp with
   * decade ticks. Returns the width it used, so the caller can put the axis
   * label beyond it.
   *
   * spec: {x, top, height, w, label, levels, colours, labels} for bands, or
   * {x, top, height, w, label, range, ramp} for a log ramp.
   */
  function colourBar(f, spec) {
    var p = f.palette;
    var x = spec.x, w = spec.w === undefined ? 13 : spec.w;
    var top = spec.top, height = spec.height;
    var g = svgEl('g');
    var lo, hi, logScale = !spec.levels;
    if (logScale) { lo = Math.log(spec.range[0]); hi = Math.log(spec.range[1]); }
    else { lo = spec.levels[0]; hi = spec.levels[spec.levels.length - 1]; }
    var span = hi - lo;
    function barY(value) {
      var a = logScale ? Math.log(value) : value;
      return top + height * (span > 0 ? (hi - a) / span : 0);
    }

    var i;
    if (logScale) {
      /* a stack of thin bands rather than an SVG gradient: a gradient needs
       * an id, and two figures on one page with the same id paint each other */
      var steps = 64;
      for (i = 0; i < steps; i += 1) {
        var y0 = top + height * (1 - (i + 1) / steps);
        g.appendChild(svgEl('rect', {
          x: x, y: y0, width: w, height: height / steps + 0.5,
          fill: rampColour(spec.ramp || 'viridis', (i + 0.5) / steps),
        }));
      }
    } else {
      for (i = 0; i < spec.levels.length - 1; i += 1) {
        var yb = barY(spec.levels[i + 1]), yt = barY(spec.levels[i]);
        g.appendChild(svgEl('rect', {
          x: x, y: yb, width: w, height: Math.max(yt - yb, 0.5),
          fill: spec.colours[i],
        }));
      }
    }
    g.appendChild(svgEl('rect', {
      x: x, y: top, width: w, height: height, fill: 'none',
      stroke: p.axis, 'stroke-width': 0.8,
    }));

    var ticks = [];
    if (logScale) {
      logTicks(spec.range).forEach(function (value) {
        ticks.push({ value: value, label: tickLabel(value) });
      });
    } else {
      /* Every band bound is labelled unless they would print on top of one
       * another, in which case every second or third one is: a bar whose
       * numbers overlap is not a scale, and the end of the range always
       * carries a number. */
      var step = Math.max(1, Math.ceil(spec.levels.length * 11 / Math.max(height, 1)));
      for (i = 0; i < spec.levels.length; i += 1) {
        if (i % step !== 0 && i !== spec.levels.length - 1) continue;
        ticks.push({
          value: spec.levels[i],
          label: spec.labels ? spec.labels[i] : C.formatG(spec.levels[i]),
        });
      }
    }
    var widest = 0;
    ticks.forEach(function (tick) {
      var y = barY(tick.value);
      if (!isFinite(y)) return;
      g.appendChild(svgEl('line', {
        x1: x + w, y1: y, x2: x + w + 3, y2: y, stroke: p.axis, 'stroke-width': 0.8,
      }));
      g.appendChild(svgEl('text', {
        x: x + w + 6, y: y + 3.4, 'font-size': 9.5, fill: p.muted, text: tick.label,
      }));
      widest = Math.max(widest, textWidth(tick.label, 9.5));
    });

    var used = w + 6 + widest;
    if (spec.label) {
      var lx = x + used + 12;
      var ly = top + height / 2;
      g.appendChild(svgEl('text', {
        x: lx, y: ly, 'font-size': 10.5, fill: p.inkSoft, 'text-anchor': 'middle',
        transform: 'rotate(-90 ' + lx + ' ' + ly + ')', text: spec.label,
      }));
      used += 24;
    }
    f.svg.appendChild(g);
    return used;
  }

  /* The horizontal axis label, and under it the note the Python prints below
   * the axes. frame() writes its xLabel on the last line of the figure, which
   * is where a note of two or three lines has to go, so a figure carrying
   * both places them here in the Python's order instead. */
  function axisLabelBelow(f, text) {
    if (!text) return;
    f.svg.appendChild(svgEl('text', {
      x: f.margin.left + f.plotW / 2, y: f.margin.top + f.plotH + 34,
      'text-anchor': 'middle', 'font-size': 11.5, fill: f.palette.inkSoft,
      text: text,
    }));
  }

  function noteBelow(f, lines, colour, size, leading) {
    lines.forEach(function (line, i) {
      f.svg.appendChild(svgEl('text', {
        x: f.margin.left + f.plotW / 2,
        y: f.margin.top + f.plotH + 46 + i * leading,
        'text-anchor': 'middle', 'font-size': size, fill: colour, text: line,
      }));
    });
  }

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
    var p = f.palette;
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

  /* ------------------------------------------------------- subsurface maps */

  /* maps.py _format_grid's tick labels: plain metres, no thousands separator
   * and no offset, because a grid reference is copied off the axis onto a
   * field sheet and 793,500 is not what a GPS will accept. */
  function utmTickLabel(value) {
    return Math.abs(value - Math.round(value)) < 1e-6
      ? String(Math.round(value)) : C.formatG(value);
  }

  /* Which band of `levels` a value falls in.
   *
   * contourf draws nothing outside its outermost levels. The engine's levels
   * always span the data - that is what ContourSet._autolev guarantees and
   * what contourLevels mirrors - so this only ever bites on a rounding error
   * at the very edge of the range, and there a blank cell in the middle of a
   * surface would read as "not surveyed", which is a worse lie than the end
   * band's colour. */
  function bandIndex(value, levels) {
    var k;
    for (k = levels.length - 2; k > 0; k -= 1) {
      if (value >= levels[k]) return k;
    }
    return 0;
  }

  /* The banded surface, as one rectangle per run of cells sharing a band.
   *
   * The grid is 220 cells square, which is 48,400 rectangles drawn one at a
   * time and an SVG no reader would wait for. Cells in a row that fall in the
   * same band are one rectangle instead, which a smooth interpolated surface
   * reduces to a couple of dozen a row. Cells the hull clip blanked are left
   * out entirely, so the page shows through exactly where the Python's mask
   * shows the page. */
  function drawSurfaceBands(parent, f, grid, levels, colours, opacity) {
    /* The alpha goes on the group, not on each cell, and neighbouring cells
     * are grown a half pixel so they overlap. Abutting SVG rectangles are
     * anti-aliased against the page and leave a pale seam along every join,
     * which drew a hatched surface of white hairlines across the map; making
     * them overlap at full alpha inside one translucent group closes the
     * seam without the overlap printing as a darker line.
     *
     * The attribute has to be `opacity` and not `fill-opacity`: a group's
     * fill-opacity is inherited by each child and applied to each shape on
     * its own, so every overlap composited twice and the hairlines came back
     * as darker ones. `opacity` composites the group once, which is what
     * contourf's one tessellated polygon per band amounts to. */
    var group = svgEl('g', { opacity: opacity });
    parent.appendChild(group);
    var dx = grid.nx > 1 ? (grid.x[grid.nx - 1] - grid.x[0]) / (grid.nx - 1) : 1;
    var dy = grid.ny > 1 ? (grid.y[grid.ny - 1] - grid.y[0]) / (grid.ny - 1) : 1;
    var bleed = 0.5, j, i;
    for (j = 0; j < grid.ny; j += 1) {
      var yTop = f.fy(Math.min(grid.y[j] + dy / 2, grid.y[grid.ny - 1]));
      var yBot = f.fy(Math.max(grid.y[j] - dy / 2, grid.y[0]));
      var runStart = -1, runBand = -1;
      for (i = 0; i <= grid.nx; i += 1) {
        var value = i < grid.nx ? grid.z[j * grid.nx + i] : null;
        var band = value === null || value === undefined
          ? -1 : bandIndex(value, levels);
        if (band === runBand) continue;
        if (runBand >= 0) {
          var xa = f.fx(Math.max(grid.x[runStart] - dx / 2, grid.x[0]));
          var xb = f.fx(Math.min(grid.x[i - 1] + dx / 2, grid.x[grid.nx - 1]));
          /* the run being closed is coloured by the band it held, not by the
           * band of the cell that ended it: painting it with `band` shifted
           * every run one band along the ramp and left the last run of each
           * row with no colour at all */
          group.appendChild(svgEl('rect', {
            x: xa - bleed, y: yTop - bleed,
            width: Math.max(xb - xa, 0.6) + 2 * bleed,
            height: Math.max(yBot - yTop, 0.6) + 2 * bleed,
            fill: colours[runBand],
          }));
        }
        runBand = band;
        runStart = i;
      }
    }
  }

  /* The white contour lines matplotlib draws over the bands.
   *
   * ax.contour(levels=cs.levels, colors="white") is not decoration on these
   * maps: it is what makes a band boundary a line a reader can follow across
   * the sheet, and what a depth is read off. Marching squares over the same
   * grid, one path per level, with any cell the hull clip blanked left out -
   * a contour has to stop where the measurements do. */
  function contourLinePaths(grid, levels) {
    var paths = [], li;
    for (li = 0; li < levels.length; li += 1) paths.push([]);
    var nx = grid.nx, z = grid.z, j, i;
    for (j = 0; j < grid.ny - 1; j += 1) {
      for (i = 0; i < nx - 1; i += 1) {
        var bl = z[j * nx + i], br = z[j * nx + i + 1];
        var tl = z[(j + 1) * nx + i], tr = z[(j + 1) * nx + i + 1];
        if (bl === null || br === null || tl === null || tr === null) continue;
        var lo = Math.min(bl, br, tl, tr), hi = Math.max(bl, br, tl, tr);
        var x0 = grid.x[i], x1 = grid.x[i + 1];
        var y0 = grid.y[j], y1 = grid.y[j + 1];
        for (li = 0; li < levels.length; li += 1) {
          var level = levels[li];
          if (level <= lo || level > hi) continue;
          /* the four edge crossings, in the order bottom, right, top, left */
          var pts = [];
          if ((bl > level) !== (br > level)) {
            pts.push([x0 + (x1 - x0) * (level - bl) / (br - bl), y0]);
          } else { pts.push(null); }
          if ((br > level) !== (tr > level)) {
            pts.push([x1, y0 + (y1 - y0) * (level - br) / (tr - br)]);
          } else { pts.push(null); }
          if ((tl > level) !== (tr > level)) {
            pts.push([x0 + (x1 - x0) * (level - tl) / (tr - tl), y1]);
          } else { pts.push(null); }
          if ((bl > level) !== (tl > level)) {
            pts.push([x0, y0 + (y1 - y0) * (level - bl) / (tl - bl)]);
          } else { pts.push(null); }
          var present = [];
          var e;
          for (e = 0; e < 4; e += 1) if (pts[e]) present.push(e);
          if (present.length === 2) {
            paths[li].push([pts[present[0]], pts[present[1]]]);
          } else if (present.length === 4) {
            /* A saddle: the same four crossings join up two different ways
             * and the cell centre decides which, the way matplotlib's own
             * contour generator decides it. Pairing them the other way puts
             * a cross through the cell instead of two corners cut off. */
            var mean = (bl + br + tl + tr) / 4;
            if ((mean > level) === (bl > level)) {
              paths[li].push([pts[0], pts[1]]);
              paths[li].push([pts[2], pts[3]]);
            } else {
              paths[li].push([pts[0], pts[3]]);
              paths[li].push([pts[1], pts[2]]);
            }
          }
        }
      }
    }
    return paths;
  }

  /* maps.py _scale_bar: a bar a round number of metres long, near a quarter of
   * the width of the map.
   *
   * `floorY` is how far down the bar may be drawn. A survey on one line gets
   * a two-line note across the foot of the axes, and the Python's fixed 5%
   * of the height puts the bar straight through it - the one figure where
   * the bar matters most, because the map has no surface on it to read. */
  function utmScaleBar(f, extent, floorY) {
    var p = f.palette;
    var x0 = extent[0], x1 = extent[1], y0 = extent[2], y1 = extent[3];
    var span = x1 - x0;
    var nice = Math.pow(10, Math.floor(Math.log(span / 4.0) / Math.LN10));
    var mults = [5, 2, 1], m;
    for (m = 0; m < mults.length; m += 1) {
      if (nice * mults[m] <= span / 4.0) { nice *= mults[m]; break; }
    }
    var bx = x0 + span * 0.06;
    var by = y0 + (y1 - y0) * 0.05;
    var py = floorY === undefined ? f.fy(by) : Math.min(f.fy(by), floorY);
    f.svg.appendChild(svgEl('line', {
      x1: f.fx(bx), y1: py, x2: f.fx(bx + nice), y2: py,
      stroke: p.ink, 'stroke-width': 3.2, 'stroke-linecap': 'butt',
    }));
    f.svg.appendChild(svgEl('line', {
      x1: f.fx(bx), y1: py, x2: f.fx(bx + nice / 2), y2: py,
      stroke: p.surface, 'stroke-width': 1.5, 'stroke-linecap': 'butt',
    }));
    f.svg.appendChild(svgEl('text', {
      x: f.fx(bx + nice / 2), y: py - 5,
      'text-anchor': 'middle', 'font-size': 9, fill: p.ink,
      stroke: p.surface, 'stroke-width': 2.6, 'paint-order': 'stroke',
      text: nice >= 1000 ? C.formatG(nice / 1000) + ' km' : C.formatG(nice) + ' m',
    }));
  }

  /* maps.py _north_arrow. */
  function utmNorthArrow(f, extent) {
    var p = f.palette;
    var x0 = extent[0], x1 = extent[1], y0 = extent[2], y1 = extent[3];
    var x = x1 - (x1 - x0) * 0.07;
    var y = y1 - (y1 - y0) * 0.16;
    var dy = (y1 - y0) * 0.09;
    var px = f.fx(x), pyBase = f.fy(y), pyTip = f.fy(y + dy);
    f.svg.appendChild(svgEl('line', {
      x1: px, y1: pyBase, x2: px, y2: pyTip + 5,
      stroke: p.ink, 'stroke-width': 1.6,
    }));
    f.svg.appendChild(svgEl('path', {
      d: 'M' + px + ' ' + pyTip + 'L' + (px - 4) + ' ' + (pyTip + 8) +
        'L' + (px + 4) + ' ' + (pyTip + 8) + 'Z',
      fill: p.ink,
    }));
    f.svg.appendChild(svgEl('text', {
      x: px, y: pyTip - 4, 'text-anchor': 'middle', 'font-size': 10,
      'font-weight': 700, fill: p.ink, stroke: p.surface, 'stroke-width': 2.6,
      'paint-order': 'stroke', text: 'N',
    }));
  }

  /* One of the four subsurface maps of mapping/subsurface.py: depth to
   * bedrock, interpreted aquifer thickness, bedrock surface elevation and
   * aquifer protective capacity. `data` is one entry of C.subsurfaceMapSet, so
   * the grid, the levels, the class table, the station text and the on-figure
   * note are all the Python's; this draws them.
   *
   * The three continuous maps are a banded fill on their own colour ramp with
   * a bar beside them; protective capacity is drawn in its five standard
   * classes with a key instead, because the decision it informs is
   * categorical and a smooth ramp invites reading a difference between 0.68
   * and 0.71 siemens that the method does not support.
   *
   * options: {width, zone} - the UTM zone goes on the axis, because two
   * eastings in different zones are not comparable numbers.
   */
  function subsurfaceMap(data, options) {
    if (!data || data.reason) return null;
    var opts = options || {};
    var extent = data.extent;
    if (!extent) return null;
    var x0 = extent[0], x1 = extent[1], y0 = extent[2], y1 = extent[3];

    var width = opts.width || 680;
    var height = Math.round(width *
      C.mapFigureHeightIn(FIGURE_WIDTH_IN, x0, x1, y0, y1) / FIGURE_WIDTH_IN);
    /* the classed map keys itself in a legend inside the frame, so it needs
     * no room beside the axes for a bar */
    var margin = { top: 30, right: data.classed ? 22 : 104, bottom: 52, left: 74 };
    var availW = width - margin.left - margin.right;
    var availH = height - margin.top - margin.bottom;
    /* _format_grid's set_aspect("equal"): a metre east is a metre north, so
     * the box shrinks to the shape of the ground rather than stretching it. A
     * map whose two axes are drawn at different scales is not a map, and a
     * scale bar on one is wrong in one direction. */
    var want = (y1 - y0) / Math.max(x1 - x0, 1e-9);
    var boxW = availW, boxH = availW * want;
    if (boxH > availH) { boxH = availH; boxW = availH / Math.max(want, 1e-9); }
    margin.left += (availW - boxW) / 2;
    margin.right += (availW - boxW) / 2;
    margin.top += (availH - boxH) / 2;
    margin.bottom += (availH - boxH) / 2;

    var labels = (opts.zone === null || opts.zone === undefined)
      ? { x: 'Easting (m)', y: 'Northing (m)' } : C.mapAxisLabels(opts.zone);
    function tickSet(lo, hi) {
      return C.mapGridTicks(lo, hi).filter(function (v) {
        return v >= lo && v <= hi;
      }).map(function (v) {
        return { value: v, label: utmTickLabel(v) };
      });
    }
    var f = frame({
      width: width, height: height, margin: margin,
      title: opts.title || data.title,
      xLabel: labels.x, yLabel: labels.y,
      xDomain: [x0, x1], yDomain: [y0, y1],
      xTicks: tickSet(x0, x1), yTicks: tickSet(y0, y1),
    });
    var p = f.palette;

    var levels = data.levels || [];
    var colours = [];
    var k;
    if (data.classed) {
      (data.classes || []).forEach(function (klass) { colours.push(klass[3]); });
    } else {
      for (k = 0; k < levels.length - 1; k += 1) {
        var mid = (levels[k] + levels[k + 1]) / 2;
        var spread = levels[levels.length - 1] - levels[0];
        colours.push(rampColour(data.cmap,
          spread > 0 ? (mid - levels[0]) / spread : 0.5));
      }
    }

    if (data.grid && levels.length > 1) {
      /* the same alpha the Python fills with, so the coordinate grid reads
       * through the surface on both figures */
      drawSurfaceBands(f.plot, f, data.grid, levels, colours,
        data.classed ? 0.8 : 0.9);
      if (!data.classed) {
        contourLinePaths(data.grid, levels).forEach(function (segments) {
          if (!segments.length) return;
          var d = '';
          segments.forEach(function (seg) {
            d += 'M' + f.fx(seg[0][0]).toFixed(1) + ' ' + f.fy(seg[0][1]).toFixed(1) +
              'L' + f.fx(seg[1][0]).toFixed(1) + ' ' + f.fy(seg[1][1]).toFixed(1);
          });
          f.plot.appendChild(svgEl('path', {
            d: d, fill: 'none', stroke: ON_RAMP_INK, 'stroke-width': 0.7,
          }));
        });
      }
    }

    /* The stations, as _interpolated_map draws them: a white-faced ring at
     * every peg, its label beside it, and the value under the label only when
     * no surface was drawn to carry it. The station is the measurement; the
     * surface between the stations is an interpolation, and the figure has to
     * let a reader tell the two apart. */
    (data.points || []).forEach(function (point) {
      var px = f.fx(point.easting), py = f.fy(point.northing);
      f.svg.appendChild(marker(px, py, 'circle',
        point.colour || p.surface, p.ink, point.colour ? 7 : 4.5));
      var lines = String(point.text === undefined ? point.label : point.text)
        .split('\n');
      /* a label on the right-hand edge runs off the frame, so it is written
       * back into the map instead - the same rule drawMapPoints follows */
      var offset = point.colour ? 9 : 6;
      var widest = lines.reduce(function (m, line) {
        return Math.max(m, textWidth(line, 9));
      }, 0);
      var flip = px + offset + widest > f.margin.left + f.plotW;
      lines.forEach(function (line, i) {
        f.svg.appendChild(svgEl('text', {
          x: px + (flip ? -offset : offset), y: py - 6 + i * 11,
          'text-anchor': flip ? 'end' : 'start', 'font-size': 9,
          'font-weight': 700, fill: p.ink, stroke: p.surface,
          'stroke-width': 2.8, 'paint-order': 'stroke', text: line,
        }));
      });
    });

    /* The note is on the figure, not in a caption: a caption can be skipped,
     * and "the survey points lie on one line and enclose no area" is the
     * difference between a map and a row of numbers. */
    var noteLines = data.note ? wrapText(data.note, f.plotW - 16, 9) : [];
    noteLines.forEach(function (line, i) {
      f.svg.appendChild(svgEl('text', {
        x: f.margin.left + f.plotW / 2,
        y: f.margin.top + f.plotH - 6 - (noteLines.length - 1 - i) * 11,
        'text-anchor': 'middle', 'font-size': 9, fill: p.critical,
        stroke: p.surface, 'stroke-width': 2.8, 'paint-order': 'stroke',
        text: line,
      }));
    });

    utmScaleBar(f, extent, f.margin.top + f.plotH - 6 - noteLines.length * 11 - 6);
    utmNorthArrow(f, extent);

    if (data.classed) {
      /* PROTECTIVE_CLASSES is one table: the class a sounding is rated
       * against, the colour of its peg and the words in this key all read
       * from it, so the map and the report cannot disagree about what
       * "moderate" means. */
      var entries = (data.legend || []).map(function (item) {
        return { label: item.label, kind: 'square', colour: item.colour };
      });
      if (entries.length) {
        var boxWide = 30 + entries.reduce(function (m, e) {
          return Math.max(m, textWidth(e.label, 11));
        }, 0) + 7;
        /* the corner is chosen for a box that already includes the title
         * line, or the key lands on the pegs it is meant to explain */
        var spot = freeCorner(f, (data.points || []).map(function (point) {
          return { px: f.fx(point.easting), py: f.fy(point.northing) };
        }), boxWide, entries.length * 17 + 6 + (data.legend_title ? 18 : 0));
        /* in a top corner the key starts at a fixed inset, so the title line
         * has to make its own room or it is written across the figure's */
        var legendY = spot.y + (spot.cy === 0 && data.legend_title ? 18 : 0);
        legend(f, entries, { x: spot.x, y: legendY });
        if (data.legend_title) {
          f.svg.appendChild(svgEl('text', {
            x: spot.x - 7, y: legendY - 18, 'font-size': 9, fill: p.muted,
            'letter-spacing': '0.04em', text: data.legend_title,
          }));
        }
      }
    } else if (data.grid && levels.length > 1) {
      colourBar(f, {
        x: f.margin.left + f.plotW + Math.max(10, f.plotW * 0.02),
        top: f.margin.top + f.plotH * 0.075, height: f.plotH * 0.85,
        levels: levels, colours: colours, labels: data.level_labels,
        label: data.cbar_label,
      });
    }

    return f.svg;
  }

  /* All four maps in the order reporting/geophysical.py plans them, each
   * either an <svg> or null with the reason beside it, so the report layer can
   * write "<name>: <reason>" for the ones the survey cannot support without
   * losing the ones it can. */
  function subsurfaceMaps(interpretations, options) {
    return C.subsurfaceMapSet(interpretations, options).map(function (data) {
      return {
        key: data.key, name: data.name, title: data.title,
        reason: data.reason || null, data: data,
        svg: data.reason ? null : subsurfaceMap(data, options),
      };
    });
  }

  /* ------------------------------------------ the drill-target suitability map */

  /* maps.py suitability_map: the scored VES points on the ground they were
   * surveyed on, coloured by the confidence-weighted score. `data` is what
   * C.suitabilityMapData returned, so the pegs, the surface, the star, the
   * legend wording and the tie note are all the Python's; this draws them.
   *
   * The figure exists so that somebody walks to one peg and not to the other,
   * which is why the recommended target is a star with its grid coordinates
   * beside it and why a tie takes the star off both points and says on the
   * face of the map why it is not there.
   *
   * options: {width, zone, title} - the zone defaults to the one the engine
   * inferred, because two eastings in different zones are not comparable
   * numbers and a map that does not say which zone it is in cannot be walked
   * back to.
   */
  function suitabilityMap(data, options) {
    if (!data || data.reason) return null;
    var opts = options || {};
    var extent = data.extent;
    if (!extent) return null;
    var x0 = extent[0], x1 = extent[1], y0 = extent[2], y1 = extent[3];

    var width = opts.width || 680;
    var height = Math.round(width *
      C.mapFigureHeightIn(FIGURE_WIDTH_IN, x0, x1, y0, y1) / FIGURE_WIDTH_IN);
    /* room on the right for the colour bar only where a surface was drawn;
     * a two-point survey has no bar and no reason to lose the width to one */
    var margin = { top: 30, right: data.surface ? 104 : 22, bottom: 52, left: 74 };
    var availW = width - margin.left - margin.right;
    var availH = height - margin.top - margin.bottom;
    /* _format_grid's set_aspect("equal"): a metre east is a metre north. A
     * map whose axes are drawn at different scales is not a map, and the
     * scale bar on it is wrong in one direction. */
    var want = (y1 - y0) / Math.max(x1 - x0, 1e-9);
    var boxW = availW, boxH = availW * want;
    if (boxH > availH) { boxH = availH; boxW = availH / Math.max(want, 1e-9); }
    margin.left += (availW - boxW) / 2;
    margin.right += (availW - boxW) / 2;
    margin.top += (availH - boxH) / 2;
    margin.bottom += (availH - boxH) / 2;

    var zone = (opts.zone === null || opts.zone === undefined) ? data.zone : opts.zone;
    var labels = (zone === null || zone === undefined)
      ? { x: 'Easting (m)', y: 'Northing (m)' } : C.mapAxisLabels(zone);
    function tickSet(lo, hi) {
      return C.mapGridTicks(lo, hi).filter(function (v) {
        return v >= lo && v <= hi;
      }).map(function (v) {
        return { value: v, label: utmTickLabel(v) };
      });
    }
    var f = frame({
      width: width, height: height, margin: margin,
      title: opts.title || data.title,
      xLabel: labels.x, yLabel: labels.y,
      xDomain: [x0, x1], yDomain: [y0, y1],
      xTicks: tickSet(x0, x1), yTicks: tickSet(y0, y1),
    });
    var p = f.palette;

    var levels = data.levels || [];
    var lo = levels.length ? levels[0] : 0;
    var span = levels.length ? levels[levels.length - 1] - lo : 1;
    var colours = [], k;
    for (k = 0; k < levels.length - 1; k += 1) {
      var mid = (levels[k] + levels[k + 1]) / 2;
      colours.push(rampColour(data.cmap || 'RdYlGn', span > 0 ? (mid - lo) / span : 0.5));
    }

    if (data.grid && levels.length > 1) {
      /* the same alpha contourf fills with, so the coordinate grid reads
       * through the surface on both figures. No white contour lines: the
       * Python draws none on this map, and a line drawn where it draws none
       * would read as a boundary between two suitabilities rather than as
       * the smooth interpolation it is. */
      drawSurfaceBands(f.plot, f, data.grid, levels, colours, 0.75);
    }

    /* The pegs. Every surveyed point is drawn, scored or not, and the one
     * the report recommends is the star: a point the scorecard could not
     * value is still a station somebody occupied, and leaving it off the map
     * would hide it from the reader deciding where to drill. */
    (data.points || []).forEach(function (point) {
      var px = f.fx(point.easting), py = f.fy(point.northing);
      var colour = (point.value === null || point.value === undefined)
        ? p.muted : rampColour(data.cmap || 'RdYlGn', Number(point.value) / 100.0);
      f.svg.appendChild(marker(px, py, point.recommended ? 'star' : 'circle',
        colour, p.ink, point.recommended ? 9 : 8));
      var lines = String(point.text === undefined ? point.label : point.text)
        .split('\n');
      /* a label on the right-hand edge runs off the frame, so it is written
       * back into the map instead - the same rule subsurfaceMap follows */
      var offset = point.recommended ? 15 : 11;
      var widest = lines.reduce(function (m, line) {
        return Math.max(m, textWidth(line, 9));
      }, 0);
      var flip = px + offset + widest > f.margin.left + f.plotW;
      lines.forEach(function (line, i) {
        f.svg.appendChild(svgEl('text', {
          x: px + (flip ? -offset : offset), y: py - 6 + i * 11,
          'text-anchor': flip ? 'end' : 'start', 'font-size': 9,
          'font-weight': point.recommended ? 700 : 400, fill: p.ink,
          stroke: p.surface, 'stroke-width': 2.8, 'paint-order': 'stroke',
          text: line,
        }));
      });
    });

    /* Why there is no star, across the top of the map. It belongs on the
     * figure and not only in the caption: a reader who sees two pegs of the
     * same colour and no star reads the omission as an oversight unless the
     * map says the two cannot be told apart. */
    var tieLines = data.tie_note ? wrapText(data.tie_note, f.plotW - 16, 9) : [];
    tieLines.forEach(function (line, i) {
      f.svg.appendChild(svgEl('text', {
        x: f.margin.left + f.plotW / 2,
        y: f.margin.top + f.plotH * 0.035 + 9 + i * 11,
        'text-anchor': 'middle', 'font-size': 9, fill: p.critical,
        stroke: p.surface, 'stroke-width': 2.8, 'paint-order': 'stroke',
        text: line,
      }));
    });

    /* and, at the foot, that there is no surface between the pegs at all */
    var noteLines = data.note ? wrapText(data.note, f.plotW - 16, 9) : [];
    noteLines.forEach(function (line, i) {
      f.svg.appendChild(svgEl('text', {
        x: f.margin.left + f.plotW / 2,
        y: f.margin.top + f.plotH - 6 - (noteLines.length - 1 - i) * 11,
        'text-anchor': 'middle', 'font-size': 9, fill: p.critical,
        stroke: p.surface, 'stroke-width': 2.8, 'paint-order': 'stroke',
        text: line,
      }));
    });

    /* Everything that sits along the foot of the map is lifted clear of the
     * note, scale bar and legend alike. On the one figure where the note
     * matters most - a survey on one line, with no surface on the map to
     * read - the legend was printed across the end of the sentence saying
     * there is no surface. */
    var floorY = f.margin.top + f.plotH - 6 - noteLines.length * 11;
    utmScaleBar(f, extent, floorY - 6);
    utmNorthArrow(f, extent);

    /* loc="lower right", where the Python pins it: the scale bar has the
     * lower left and the north arrow the upper right, and the tie note runs
     * across the top. */
    var entries = (data.legend || []).map(function (item) {
      /* the swatch is the marker of the point that registered the entry, as
       * matplotlib's legend handle is: a key drawn in a colour no peg on the
       * map carries says the colour means nothing */
      return {
        label: item.label, kind: item.kind || 'circle',
        colour: (item.value === null || item.value === undefined) ? p.muted
          : rampColour(data.cmap || 'RdYlGn', Number(item.value) / 100.0),
      };
    });
    if (entries.length) {
      var legendW = 30 + entries.reduce(function (m, entry) {
        return Math.max(m, textWidth(entry.label, 11));
      }, 0) + 7;
      legend(f, entries, {
        x: f.margin.left + f.plotW - legendW + 3,
        y: floorY - 5 - entries.length * 17,
      });
    }

    if (data.grid && levels.length > 1) {
      colourBar(f, {
        x: f.margin.left + f.plotW + Math.max(10, f.plotW * 0.02),
        top: f.margin.top + f.plotH * 0.075, height: f.plotH * 0.85,
        levels: levels, colours: colours, label: data.cbar_label,
      });
    }

    return f.svg;
  }

  /* --------------------------------------------------- the ground profile */

  /* mapping/terrain.py plot_ground_profile: the land surface along the
   * traverse, from the elevation the crew recorded at each sounding, against
   * chainage. `data` is what C.groundProfileData returned; a survey that
   * cannot support the figure returns null there and nothing is drawn here,
   * because reporting/geophysical.py omits this figure silently rather than
   * drawing a ground surface it did not measure.
   *
   * The line between two stations is drawn straight and the figure says so:
   * the elevations are measured at the pegs and nothing was levelled between
   * them.
   */
  function groundProfile(data, options) {
    if (!data || data.reason) return null;
    var opts = options || {};
    var stations = data.stations || [];
    var known = stations.filter(function (station) {
      return station.elevation_m !== null && station.elevation_m !== undefined;
    });
    if (known.length < 2) return null;

    var width = opts.width || 680;
    /* figsize=(figure_width_in, 2.6): a profile is a strip, and drawn any
     * taller it exaggerates a metre of relief over 200 m of traverse into a
     * hillside */
    var height = opts.height || Math.round(width * 2.6 / FIGURE_WIDTH_IN);
    var elevations = known.map(function (station) { return station.elevation_m; });
    var baseline = data.baseline_m;
    /* matplotlib autoscales with a 5 per cent margin either side, and the
     * fill reaches below the lowest level, so the axis has to hold it */
    var f = frame({
      width: width, height: height, margin: { top: 30, right: 22, bottom: 46, left: 66 },
      title: opts.title || data.title,
      xLabel: data.x_label, yLabel: data.y_label,
      /* the drawn stations set the span, as matplotlib's autoscale does:
       * plot_ground_profile plots and fills over the levelled stations only,
       * so a station with no recorded elevation adds no empty axis beside
       * the profile */
      xDomain: padDomain(known.map(function (station) {
        return station.chainage_m;
      }), false, 0.05),
      yDomain: padDomain(elevations.concat([baseline]), false, 0.05),
    });
    var p = f.palette;

    var pts = known.map(function (station) {
      return [f.fx(station.chainage_m), f.fy(station.elevation_m)];
    });
    /* the ground drawn as a solid rather than as a line floating on the
     * axis: fill_between(chainage, elevation, nanmin(elevation) - 2), one
     * run of stations at a time, so no line and no fill crosses a gap wider
     * than the soundings reach - a straight line across one is a slope
     * nobody levelled */
    var base = f.fy(baseline);
    var runs = data.runs || [stations.map(function (station, k) { return k; })
      .filter(function (k) {
        return stations[k].elevation_m !== null && stations[k].elevation_m !== undefined;
      })];
    runs.forEach(function (run) {
      var seg = run.map(function (k) {
        return [f.fx(stations[k].chainage_m), f.fy(stations[k].elevation_m)];
      });
      if (!seg.length) return;
      var fill = 'M' + seg[0][0].toFixed(2) + ' ' + base.toFixed(2);
      seg.forEach(function (pt) {
        fill += 'L' + pt[0].toFixed(2) + ' ' + pt[1].toFixed(2);
      });
      fill += 'L' + seg[seg.length - 1][0].toFixed(2) + ' ' + base.toFixed(2) + 'Z';
      f.plot.appendChild(svgEl('path', {
        d: fill, fill: p.accent, 'fill-opacity': 0.08, stroke: 'none',
      }));
      if (seg.length > 1) {
        f.plot.appendChild(polyline(seg, { stroke: p.accent, 'stroke-width': 1.8 }));
      }
    });
    known.forEach(function (station, k) {
      var mark = marker(pts[k][0], pts[k][1], 'circle', p.surface, p.accent, 4);
      mark.appendChild(svgEl('title', {
        text: station.label + ': ' + C.formatG(station.elevation_m) + ' m at ' +
          C.formatG(station.chainage_m) + ' m',
      }));
      f.plot.appendChild(mark);
    });

    /* the station names on the figure: a profile with no names on it cannot
     * be compared with the section or the map drawn from the same traverse */
    stations.forEach(function (station, k) {
      if (station.elevation_m === null || station.elevation_m === undefined) return;
      if (!station.label) return;
      f.svg.appendChild(svgEl('text', {
        x: f.fx(station.chainage_m), y: f.fy(station.elevation_m) - 11,
        'text-anchor': 'middle', 'font-size': 7.5, 'font-weight': 700,
        fill: p.ink, stroke: p.surface, 'stroke-width': 2.6,
        'paint-order': 'stroke', text: station.label,
      }));
    });

    /* A station whose level nobody recorded is not drawn, and the figure
     * says how many, inside the axes where the Python puts it: the line runs
     * straight across that ground, and without the note it reads as a slope
     * somebody levelled. */
    var noteLines = data.note ? wrapText(data.note, f.plotW - 16, 7) : [];
    noteLines.forEach(function (line, i) {
      f.svg.appendChild(svgEl('text', {
        x: f.margin.left + f.plotW / 2,
        y: f.margin.top + f.plotH - 4 - (noteLines.length - 1 - i) * 9,
        'text-anchor': 'middle', 'font-size': 7, fill: p.critical,
        stroke: p.surface, 'stroke-width': 2.4, 'paint-order': 'stroke',
        text: line,
      }));
    });

    legend(f, [{ label: data.series_label, kind: 'line', colour: p.accent }], {
      avoid: pts.map(function (pt) { return { px: pt[0], py: pt[1] }; }),
    });
    return f.svg;
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
    /* The survey's own figures. Each takes what gwt-core.js mirrored out of
     * the Python and returns null where the Python refused to draw, so the
     * report prints the engine's reason instead of an empty frame. */
    geoelectricSection: geoelectricSection,
    modelPseudosection: modelPseudosection,
    apparentPseudosection: apparentPseudosection,
    subsurfaceMap: subsurfaceMap, subsurfaceMaps: subsurfaceMaps,
    suitabilityMap: suitabilityMap, groundProfile: groundProfile,
    rampColour: rampColour, colourRamps: COLOUR_RAMPS, colourBar: colourBar,
    testOverview: testOverview, cooperJacob: cooperJacob,
    recovery: recoveryPlot, stepTest: stepTestPlot,
    piper: piper, stiff: stiff, boreholeDesign: boreholeDesign,
    lithologyColour: lithologyColour,
    depthSpine: depthSpine, guidelineSpine: guidelineSpine,
    costBreakdown: costBreakdown, programmeGantt: programmeGantt,
    choropleth: choropleth, siteMap: siteMap, thematicMap: thematicMap,
    studyAreaMap: studyAreaMap, studyAreaRadiusKm: studyAreaRadiusKm,
    chiefdomLabel: chiefdomLabel, relativeLuminance: relativeLuminance,
    geologyColours: GEOLOGY_COLOURS, mapTones: {
      sea: MAP_SEA, land: MAP_LAND, foreignLand: MAP_FOREIGN_LAND,
      notMapped: MAP_NOT_MAPPED, noData: MAP_NO_DATA,
    },
    /* the caller says which sheet the layer came off; both bundled layers
     * are 1:5,000,000, and the aquifer map carries its publisher's own
     * limit on it as well */
    usePrintPalette: usePrintPalette,
    scaleCaveat: scaleCaveat, usgsSourceScale: USGS_SOURCE_SCALE,
    bgsSourceScale: BGS_SOURCE_SCALE, bgsPublisherNote: BGS_PUBLISHER_NOTE,
    mapProjection: mapProjection, projectionInto: projectionInto,
    geometryPath: geometryPath, quantileBreaks: quantileBreaks,
    pointInFeature: pointInFeature, ringInBox: ringInBox,
    declutter: declutter, graticuleStep: graticuleStep,
    textWidth: textWidth, wrapText: wrapText, ellipsise: ellipsise,
    stackLabels: stackLabels,
    toPng: toPng, downloadSvg: download, figure: figure,
  };
}(typeof window !== 'undefined' ? window : globalThis));

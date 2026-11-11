
  /* --------------------------------------------------------------- frame */

  /* On the page a figure is set in the app's own face, the stylesheet's
   * --font. A figure rasterised for a report, or saved as a file, is a
   * document of its own that the app's fonts do not reach, and it goes out
   * in the face it always has (EXPORT_FONT, put back by the export). */
  var FONT = '"Inter", "Segoe UI", system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif';
  var EXPORT_FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif';

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
    var best = /** @type {{corner: any, hits: number}|null} */ (null);
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
      } else if (entry.kind === 'down') {
        g.appendChild(downMark(x + 8, ly - 4, entry.colour, f.palette.surface));
      } else if (entry.kind === 'tick') {
        g.appendChild(svgEl('line', {
          x1: x + 8, y1: ly - 9, x2: x + 8, y2: ly + 1, stroke: entry.colour,
          'stroke-width': 1.6,
        }));
      } else if (entry.kind === 'hollow') {
        g.appendChild(marker(x + 8, ly - 4, 'circle', f.palette.surface, entry.colour));
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
      var best = /** @type {{d: number, point: any, series: any}|null} */ (null);
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

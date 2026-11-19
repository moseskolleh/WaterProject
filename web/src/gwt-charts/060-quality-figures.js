
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

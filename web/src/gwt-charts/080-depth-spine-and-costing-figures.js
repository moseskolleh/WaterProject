
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

    /* An image's contents are hidden from assistive technology, and the
     * screen handles below are sliders the keyboard moves: the editable
     * spine is a group, so that they can be found. */
    var svg = svgEl('svg', {
      viewBox: '0 0 ' + width + ' ' + height, width: '100%', xmlns: NS,
      'font-family': FONT, role: opts.readOnly ? 'img' : 'group',
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

  /* The cost as a distribution (PLAN.md step 3.4): the share of the sampled
   * costs at or under each cost, from the distribution's curve (the cost at
   * every percent), with P50 and P80 read off it and the deterministic
   * figures in `marks` ([label, usd] pairs) drawn as lines across it. The
   * same figure as costing/plots.py plot_cost_distribution. A cumulative
   * curve rather than a histogram, because P50, P80 and how much of the
   * spread a budget covers are read straight off it. */
  function costDistribution(curve, marks, options) {
    var opts = options || {};
    var xs = curve.concat(marks.map(function (m) { return m[1]; }));
    var lo = Math.min.apply(null, xs), hi = Math.max.apply(null, xs);
    var pad = 0.04 * ((hi - lo) || Math.abs(hi) || 1);
    var f = frame({
      width: opts.width || 720, height: opts.height || 340,
      margin: { top: 34, right: 26, bottom: 52, left: 66 },
      xDomain: [lo - pad, hi + pad], yDomain: [0, 100],
      title: opts.title || '',
      xLabel: 'US$ (contract price with any VAT)', yLabel: 'Sampled at or under (%)',
    });
    var p = f.palette;
    var steps = curve.length - 1;
    /* the P10 to P90 of the sample shaded behind the curve: the band the
     * cost's decision number quotes (PLAN.md step 3.6) */
    var tenth = Math.floor(steps / 10);
    f.plot.appendChild(svgEl('rect', {
      x: f.fx(curve[tenth]), y: f.fy(100),
      width: Math.max(f.fx(curve[steps - tenth]) - f.fx(curve[tenth]), 1),
      height: f.fy(0) - f.fy(100), fill: p.accent, 'fill-opacity': 0.12,
    }));
    var d = curve.map(function (x, k) {
      return (k ? 'L' : 'M') + f.fx(x).toFixed(1) + ' ' + f.fy(100 * k / steps).toFixed(1);
    }).join('');
    f.plot.appendChild(svgEl('path', { d: d, fill: 'none', stroke: p.accent,
      'stroke-width': 2 }));
    [50, 80].forEach(function (q) {
      var x = curve[Math.round(q * steps / 100)];
      f.plot.appendChild(svgEl('path', {
        d: 'M' + f.fx(curve[0]) + ' ' + f.fy(q) + 'H' + f.fx(x) + 'V' + f.fy(0),
        fill: 'none', stroke: p.neutral, 'stroke-width': 0.9, 'stroke-dasharray': '2 3',
      }));
      f.plot.appendChild(svgEl('text', {
        x: f.fx(x) + 5, y: f.fy(q) + 13, 'font-size': 10.5, fill: p.neutral,
        text: 'P' + q + ' ' + S.thousands(x, 0),
      }));
    });
    marks.forEach(function (mark, i) {
      var x = f.fx(mark[1]);
      f.plot.appendChild(svgEl('line', { x1: x, y1: f.fy(0), x2: x, y2: f.fy(100),
        stroke: p.secondary, 'stroke-width': 1.2,
        'stroke-dasharray': i ? '5 3' : null }));
      var label = mark[0] + ' ' + S.thousands(mark[1], 0);
      var right = x + 5 + textWidth(label, 10.5) > f.margin.left + f.plotW;
      f.plot.appendChild(svgEl('text', {
        x: right ? x - 5 : x + 5, y: f.fy(100) + 13 + 13 * i,
        'text-anchor': right ? 'end' : 'start', 'font-size': 10.5, fill: p.secondary,
        text: label,
      }));
    });
    return f.svg;
  }

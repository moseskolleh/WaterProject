
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
   * {x, top, height, w, label, range, ramp} for a log ramp, or the same with
   * linear: true for a ramp on a linear scale (the terrain figures).
   */
  function colourBar(f, spec) {
    var p = f.palette;
    var x = spec.x, w = spec.w === undefined ? 13 : spec.w;
    var top = spec.top, height = spec.height;
    var g = svgEl('g');
    var lo, hi, smooth = !spec.levels, logScale = smooth && !spec.linear;
    if (logScale) { lo = Math.log(spec.range[0]); hi = Math.log(spec.range[1]); }
    else if (smooth) { lo = spec.range[0]; hi = spec.range[1]; }
    else { lo = spec.levels[0]; hi = spec.levels[spec.levels.length - 1]; }
    var span = hi - lo;
    function barY(value) {
      var a = logScale ? Math.log(value) : value;
      return top + height * (span > 0 ? (hi - a) / span : 0);
    }

    var i;
    if (smooth) {
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
    } else if (smooth) {
      linTicks(spec.range, 5).forEach(function (value) {
        ticks.push({ value: value, label: C.formatG(value) });
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

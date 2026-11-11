
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
    var pegs = [];
    (data.points || []).forEach(function (point) {
      var px = f.fx(point.easting), py = f.fy(point.northing);
      var colour = (point.value === null || point.value === undefined)
        ? p.muted : rampColour(data.cmap || 'RdYlGn', Number(point.value) / 100.0);
      f.svg.appendChild(marker(px, py, point.recommended ? 'star' : 'circle',
        colour, p.ink, point.recommended ? 9 : 8));
      pegs.push({ point: point, px: px, py: py });
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
    var furniture = [utmScaleBar(f, extent, floorY - 6), utmNorthArrow(f, extent)];
    [[tieLines, f.margin.top + f.plotH * 0.035 + 9],
      [noteLines, f.margin.top + f.plotH - 6 - (noteLines.length - 1) * 11]]
      .forEach(function (block) {
        if (!block[0].length) return;
        var wide = block[0].reduce(function (m, line) {
          return Math.max(m, textWidth(line, 9));
        }, 0);
        var mid = f.margin.left + f.plotW / 2;
        furniture.push({ x0: mid - wide / 2, y0: block[1] - 9,
          x1: mid + wide / 2, y1: block[1] + (block[0].length - 1) * 11 + 3 });
      });

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
      var legendX = f.margin.left + f.plotW - legendW + 3;
      var legendY = floorY - 5 - entries.length * 17;
      legend(f, entries, { x: legendX, y: legendY });
      furniture.push({ x0: legendX - 7, y0: legendY - 13, x1: legendX - 7 + legendW,
        y1: legendY - 13 + entries.length * 17 + 6 });
    }

    if (data.grid && levels.length > 1) {
      colourBar(f, {
        x: f.margin.left + f.plotW + Math.max(10, f.plotW * 0.02),
        top: f.margin.top + f.plotH * 0.075, height: f.plotH * 0.85,
        levels: levels, colours: colours, label: data.cbar_label,
      });
    }

    placeSuitabilityLabels(f, pegs, furniture);
    return f.svg;
  }

  /* Where a label may sit around its peg, in the order they are tried, as
   * [dx, dy] in pixels with dy up (maps.py _LABEL_SLOTS): the diagonals and
   * the four quarters first and every ten degrees after them, nearest
   * first. Before any of them the label is tried where every label used to
   * be written, so a label with room there stays where it was, and then the
   * same place mirrored to the left, which is where a label that ran off
   * the right-hand edge used to be flipped to. */
  var LABEL_SLOTS = (function () {
    /** @type {Array<*>} */
    var slots = [null, 'flip'];
    var angles = [30, 150, -30, -150, 90, -90, 0, 180];
    for (var a = -170; a < 180; a += 10) {
      if (angles.indexOf(a) < 0) angles.push(a);
    }
    for (var radius = 12; radius < 330; radius += 8) {
      angles.forEach(function (angle) {
        var t = angle * Math.PI / 180;
        slots.push([radius * Math.cos(t), 0.6 * radius * Math.sin(t)]);
      });
    }
    return slots;
  }());
  /* past this distance from its peg a label is tied to it by a leader line */
  var LEADER_FROM = 16;
  /* what a leader crossing a peg or a label costs: far less than any overlap,
   * because a crossed leader is untidy and overlapping words cannot be read */
  var LEADER_CROSSING = 0.01;

  /* maps.py _separate_labels. Every label was written to the right of its
   * peg, so on a dense survey the labels ran through each other and through
   * the neighbouring pegs, and the map named nobody. Labels are placed with
   * the recommended target first, then by rank, at the first slot where the
   * label stays inside the map, clear of every peg, of the map's furniture
   * (`furniture`, boxes of {x0, y0, x1, y1}) and of the labels already
   * placed, and where its leader line, if it needs one, crosses none of
   * them, or else as few as it can. Where nothing is clear it goes where it
   * covers least. When the full labels cannot all be placed without running
   * into something, the grade line, which the table above carries for every
   * point, gives way everywhere but at the target and the labels are placed
   * again. */
  function placeSuitabilityLabels(f, pegs, furniture) {
    var p = f.palette;
    var frame = { x0: f.margin.left, y0: f.margin.top,
      x1: f.margin.left + f.plotW, y1: f.margin.top + f.plotH };
    var markers = pegs.map(function (peg) {
      var r = peg.point.recommended ? 14 : 10;
      return { x0: peg.px - r, y0: peg.py - r, x1: peg.px + r, y1: peg.py + r };
    });
    var order = pegs.slice().sort(function (a, b) {
      function key(peg) {
        var rank = peg.point.rank;
        return [peg.point.recommended ? 0 : 1,
          rank === null || rank === undefined ? 1e6 : rank];
      }
      var ka = key(a), kb = key(b);
      return ka[0] - kb[0] || ka[1] - kb[1];
    });
    function area(a, b) {
      var w = Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0);
      var h = Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0);
      return w > 0 && h > 0 ? w * h : 0;
    }
    function meets(x0, y0, x1, y1, box) {
      var lo = 0, hi = 1;
      var tests = [[-(x1 - x0), x0 - box.x0], [x1 - x0, box.x1 - x0],
        [-(y1 - y0), y0 - box.y0], [y1 - y0, box.y1 - y0]];
      for (var i = 0; i < tests.length; i++) {
        var q = tests[i][0], r = tests[i][1];
        if (q === 0) { if (r < 0) return false; continue; }
        var t = r / q;
        if (q < 0) lo = Math.max(lo, t); else hi = Math.min(hi, t);
        if (lo > hi) return false;
      }
      return true;
    }
    /* a label of `lines` at slot `slot` for `peg`: its box, the anchor and
     * first baseline it is written at, and the leader it needs */
    function layout(peg, lines, slot) {
      /* textWidth is a generic estimate; in the map's own font a label runs
       * up to a twelfth wider, and the target's bold label a quarter */
      var widest = lines.reduce(function (m, line) {
        return Math.max(m, textWidth(line, 9));
      }, 0) * (peg.point.recommended ? 1.25 : 1.1);
      var height = lines.length * 11;
      var offset = peg.point.recommended ? 15 : 11;
      if (slot === null || slot === 'flip') {
        var flip = slot === 'flip';
        var x = peg.px + (flip ? -offset : offset);
        return { anchor: flip ? 'end' : 'start', x: x, baseline: peg.py - 6,
          box: { x0: flip ? x - widest : x, y0: peg.py - 14,
            x1: flip ? x : x + widest, y1: peg.py - 14 + height },
          leader: null };
      }
      var dx = slot[0], dy = slot[1];
      var ax = peg.px + dx, ay = peg.py - dy;
      var anchor = dx > 1 ? 'start' : dx < -1 ? 'end' : 'middle';
      var x0 = anchor === 'start' ? ax : anchor === 'end' ? ax - widest : ax - widest / 2;
      var top = dy > 1 ? ay - height : dy < -1 ? ay : ay - height / 2;
      var length = Math.sqrt(dx * dx + dy * dy);
      return { anchor: anchor, x: ax, baseline: top + 8,
        box: { x0: x0, y0: top, x1: x0 + widest, y1: top + height },
        leader: length > LEADER_FROM
          ? [peg.px + dx * 10 / length, peg.py - dy * 10 / length, ax, ay] : null };
    }
    function place(textOf) {
      var obstacles = markers.concat(furniture);
      var clear = true, chosen = [];
      order.forEach(function (peg) {
        var lines = String(textOf(peg.point)).split('\n');
        var best = null;
        for (var i = 0; i < LABEL_SLOTS.length; i++) {
          var at = layout(peg, lines, LABEL_SLOTS[i]);
          var b = at.box;
          var cost = (b.x1 - b.x0) * (b.y1 - b.y0) - area(b, frame);
          obstacles.forEach(function (o) { cost += area(b, o); });
          if (at.leader) {
            var l = at.leader;
            obstacles.forEach(function (o) {
              if (meets(l[0], l[1], l[2], l[3], o)) cost += LEADER_CROSSING;
            });
          }
          if (best === null || cost < best.cost) best = { cost: cost, at: at };
          if (cost === 0) break;
        }
        /* a crossed leader is untidy but legible; only words that would
         * run into something make the map too dense for full labels */
        clear = clear && best.cost < 1;
        obstacles.push(best.at.box);
        chosen.push({ peg: peg, lines: lines, at: best.at });
      });
      return { clear: clear, chosen: chosen };
    }
    var textOf = function (point) {
      return point.text === undefined ? point.label : point.text;
    };
    var result = place(textOf);
    if (!result.clear) {
      result = place(function (point) {
        return point.compact_text === undefined ? textOf(point) : point.compact_text;
      });
    }
    result.chosen.forEach(function (item) {
      var at = item.at, point = item.peg.point;
      if (at.leader) {
        f.svg.appendChild(svgEl('line', {
          x1: at.leader[0], y1: at.leader[1], x2: at.leader[2], y2: at.leader[3],
          stroke: p.inkSoft, 'stroke-width': 0.8, 'data-leader': point.label,
        }));
      }
      item.lines.forEach(function (line, i) {
        f.svg.appendChild(svgEl('text', {
          x: at.x, y: at.baseline + i * 11,
          'text-anchor': at.anchor, 'font-size': 9,
          'font-weight': point.recommended ? 700 : 400, fill: p.ink,
          stroke: p.surface, 'stroke-width': 2.8, 'paint-order': 'stroke',
          'data-peg': point.label, text: line,
        }));
      });
    });
  }

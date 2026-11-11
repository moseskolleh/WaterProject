
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
    /* the ground it covers, so a label can be kept off it */
    return { x0: f.fx(bx) - 2, y0: py - 16, x1: f.fx(bx + nice) + 2, y1: py + 3 };
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
    return { x0: px - 8, y0: pyTip - 15, x1: px + 8, y1: pyBase + 1 };
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

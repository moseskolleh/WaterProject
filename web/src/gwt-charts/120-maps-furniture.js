
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
       * the extent alone stopped short of the neatline with map still to go.
       * A caller whose map is narrower than these passes its own step
       * (opts.step), so that its numbers do not run into each other. */
      var step = opts.step || graticuleStep(Math.max(b.lonMax - b.lonMin, b.latMax - b.latMin));
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

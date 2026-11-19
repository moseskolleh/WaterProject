
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

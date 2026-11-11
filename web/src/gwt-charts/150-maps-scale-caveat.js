
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
    var p = paperPalette();
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

    var svg = svgEl('svg', {
      viewBox: '0 0 ' + width + ' ' + height, width: '100%', xmlns: NS,
      'font-family': FONT, role: 'img', 'aria-label': spec.title || 'map',
      /* for the page only: the export takes it off again */
      'class': SHEET_CLASS,
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

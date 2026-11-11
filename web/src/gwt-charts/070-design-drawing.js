
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
    /* a design's screens are where the rules put them; only an as-built
     * record can say where they are */
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
      /* the intake is always the recommended one: an as-built record
       * carries the screens the crew set, but no record of a pump */
      callout(intake, intake, 'pump intake ' + formatG(intake) + ' m (recommended)');
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

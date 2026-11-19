
  /* --------------------------------------------------- the ground profile */

  /* mapping/terrain.py plot_ground_profile: the land surface along the
   * traverse, from the elevation the crew recorded at each sounding, against
   * chainage. `data` is what C.groundProfileData returned; a survey that
   * cannot support the figure returns null there and nothing is drawn here,
   * because reporting/geophysical.py omits this figure silently rather than
   * drawing a ground surface it did not measure.
   *
   * The line between two stations is drawn straight and the figure says so:
   * the elevations are measured at the pegs and nothing was levelled between
   * them.
   */
  function groundProfile(data, options) {
    if (!data || data.reason) return null;
    var opts = options || {};
    var stations = data.stations || [];
    var known = stations.filter(function (station) {
      return station.elevation_m !== null && station.elevation_m !== undefined;
    });
    if (known.length < 2) return null;

    var width = opts.width || 680;
    /* figsize=(figure_width_in, 2.6): a profile is a strip, and drawn any
     * taller it exaggerates a metre of relief over 200 m of traverse into a
     * hillside */
    var height = opts.height || Math.round(width * 2.6 / FIGURE_WIDTH_IN);
    var elevations = known.map(function (station) { return station.elevation_m; });
    var baseline = data.baseline_m;
    /* matplotlib autoscales with a 5 per cent margin either side, and the
     * fill reaches below the lowest level, so the axis has to hold it */
    var f = frame({
      width: width, height: height, margin: { top: 30, right: 22, bottom: 46, left: 66 },
      title: opts.title || data.title,
      xLabel: data.x_label, yLabel: data.y_label,
      /* the drawn stations set the span, as matplotlib's autoscale does:
       * plot_ground_profile plots and fills over the levelled stations only,
       * so a station with no recorded elevation adds no empty axis beside
       * the profile */
      xDomain: padDomain(known.map(function (station) {
        return station.chainage_m;
      }), false, 0.05),
      yDomain: padDomain(elevations.concat([baseline]), false, 0.05),
    });
    var p = f.palette;

    var pts = known.map(function (station) {
      return [f.fx(station.chainage_m), f.fy(station.elevation_m)];
    });
    /* the ground drawn as a solid rather than as a line floating on the
     * axis: fill_between(chainage, elevation, nanmin(elevation) - 2), one
     * run of stations at a time, so no line and no fill crosses a gap wider
     * than the soundings reach - a straight line across one is a slope
     * nobody levelled */
    var base = f.fy(baseline);
    var runs = data.runs || [stations.map(function (station, k) { return k; })
      .filter(function (k) {
        return stations[k].elevation_m !== null && stations[k].elevation_m !== undefined;
      })];
    runs.forEach(function (run) {
      var seg = run.map(function (k) {
        return [f.fx(stations[k].chainage_m), f.fy(stations[k].elevation_m)];
      });
      if (!seg.length) return;
      var fill = 'M' + seg[0][0].toFixed(2) + ' ' + base.toFixed(2);
      seg.forEach(function (pt) {
        fill += 'L' + pt[0].toFixed(2) + ' ' + pt[1].toFixed(2);
      });
      fill += 'L' + seg[seg.length - 1][0].toFixed(2) + ' ' + base.toFixed(2) + 'Z';
      f.plot.appendChild(svgEl('path', {
        d: fill, fill: p.accent, 'fill-opacity': 0.08, stroke: 'none',
      }));
      if (seg.length > 1) {
        f.plot.appendChild(polyline(seg, { stroke: p.accent, 'stroke-width': 1.8 }));
      }
    });
    known.forEach(function (station, k) {
      var mark = marker(pts[k][0], pts[k][1], 'circle', p.surface, p.accent, 4);
      mark.appendChild(svgEl('title', {
        text: station.label + ': ' + C.formatG(station.elevation_m) + ' m at ' +
          C.formatG(station.chainage_m) + ' m',
      }));
      f.plot.appendChild(mark);
    });

    /* the station names on the figure: a profile with no names on it cannot
     * be compared with the section or the map drawn from the same traverse */
    stations.forEach(function (station, k) {
      if (station.elevation_m === null || station.elevation_m === undefined) return;
      if (!station.label) return;
      f.svg.appendChild(svgEl('text', {
        x: f.fx(station.chainage_m), y: f.fy(station.elevation_m) - 11,
        'text-anchor': 'middle', 'font-size': 7.5, 'font-weight': 700,
        fill: p.ink, stroke: p.surface, 'stroke-width': 2.6,
        'paint-order': 'stroke', text: station.label,
      }));
    });

    /* A station whose level nobody recorded is not drawn, and the figure
     * says how many, inside the axes where the Python puts it: the line runs
     * straight across that ground, and without the note it reads as a slope
     * somebody levelled. */
    var noteLines = data.note ? wrapText(data.note, f.plotW - 16, 7) : [];
    noteLines.forEach(function (line, i) {
      f.svg.appendChild(svgEl('text', {
        x: f.margin.left + f.plotW / 2,
        y: f.margin.top + f.plotH - 4 - (noteLines.length - 1 - i) * 9,
        'text-anchor': 'middle', 'font-size': 7, fill: p.critical,
        stroke: p.surface, 'stroke-width': 2.4, 'paint-order': 'stroke',
        text: line,
      }));
    });

    legend(f, [{ label: data.series_label, kind: 'line', colour: p.accent }], {
      avoid: pts.map(function (pt) { return { px: pt[0], py: pt[1] }; }),
    });
    return f.svg;
  }

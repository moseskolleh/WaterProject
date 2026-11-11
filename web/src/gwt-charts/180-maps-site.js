
  /* -------------------------------------------------------------- site map */

  /* Boundaries as context, survey points as the data. Without a position the
   * map is still drawn - the district is still worth showing - but it says in
   * the legend that the site is not on it, because a locator map with no
   * locator on it is the kind of figure that gets signed off by mistake. */
  function siteMap(spec) {
    var context = spec.context || [];
    var points = spec.points || [];
    var legendItems = (spec.legendItems || []).slice();
    if (!legendItems.length) {
      points.forEach(function (point) {
        legendItems.push({
          label: point.legend || point.label || 'Site',
          colour: point.colour || paperPalette().secondary,
          kind: point.kind || 'diamond',
        });
      });
    }
    if (!points.length) {
      legendItems.push({ label: 'no position recorded for this site',
        colour: MAP_NO_DATA });
    }

    var extent = context.length ? context : points.map(function (pt) {
      return { geometry: { type: 'Polygon', coordinates: [[[pt.lon, pt.lat]]] } };
    });
    /* a lone point projects to a degenerate extent; give it a window it can
     * actually be seen in */
    if (!context.length && points.length) {
      var pad = (spec.radiusKm || 25) / 110.574;
      extent = [{ geometry: { type: 'Polygon', coordinates: [[
        [points[0].lon - pad, points[0].lat - pad],
        [points[0].lon + pad, points[0].lat - pad],
        [points[0].lon + pad, points[0].lat + pad],
        [points[0].lon - pad, points[0].lat + pad],
      ]] } }];
    }

    var canvas = mapCanvas(spec, legendItems, extent);
    var p = canvas.palette;
    clipToFrame(canvas);
    /* A location map of a coastal district is half Atlantic and the rest of
     * the frame is Guinea; drawn as the page, both read as blank paper and
     * the coastline looked like the edge of the data. The national outline
     * is taken from the context layer when the caller has not named it,
     * because that is how the boundary layers arrive. */
    var outline = spec.outline || context.filter(function (feature) {
      return (feature.properties || {}).level === 'ADM0';
    });
    seaAndNeighbours(canvas, outline, MAP_LAND,
      foreignLandFeatures(canvas.project.visibleBox()));
    context.forEach(function (feature) {
      canvas.layer.appendChild(svgEl('path', {
        d: geometryPath(feature.geometry, canvas.project),
        'fill-rule': 'evenodd',
        fill: spec.contextFill ? spec.contextFill(feature) : '#EDEAE3',
        stroke: p.axis, 'stroke-width': 0.7,
      }, [svgEl('title', {
        text: String((feature.properties || {}).name ||
          (feature.properties || {}).shapeName || ''),
      })]));
    });
    /* Karene and Falaba have no polygon of their own in the boundary layer,
     * which predates them, so a locator for either lights the chiefdoms the
     * crosswalk assigns to it, over the district they were split from, as
     * plot_admin_map does. Lit by name alone, the district was never lit and
     * the legend named it in a colour that was nowhere on the map. */
    var highlight = spec.highlight || [];
    highlight.forEach(function (feature) {
      canvas.layer.appendChild(svgEl('path', {
        d: geometryPath(feature.geometry, canvas.project),
        'fill-rule': 'evenodd', fill: spec.highlightFill || '#CFE0D6',
        stroke: '#7E93A6', 'stroke-width': 0.5,
      }));
    });
    /* The districts were drawn as shapes with a hover title and nothing
     * written on them, so a printed location map named no district at all.
     * The same declutter the study-area map uses keeps a name off its
     * neighbours and off the frame. */
    if (spec.labelContext) {
      var nameBox = canvas.project.visibleBox();
      var nameCandidates = [];
      /* a district lit through its chiefdoms is named once, over them, and
       * first, so the declutter keeps it over the older district's name */
      if (highlight.length && spec.highlightLabel) {
        var sx = 0, sy = 0, count = 0;
        highlight.forEach(function (feature) {
          ringsOf(feature.geometry).forEach(function (ring) {
            ring.forEach(function (c) { sx += c[0]; sy += c[1]; count += 1; });
          });
        });
        if (count) nameCandidates.push([sx / count, sy / count, spec.highlightLabel]);
      }
      context.forEach(function (feature) {
        var props = feature.properties || {};
        var text = String(props.name || props.shapeName || '');
        if (!text) return;
        var rings = ringsOf(feature.geometry);
        if (!rings.length) return;
        var centre = ringCentroid(rings[0]);
        nameCandidates.push([centre[0], centre[1], text]);
      });
      declutter(nameCandidates, nameBox, 0.06).forEach(function (candidate) {
        var at = canvas.project(candidate[0], candidate[1]);
        placeMapLabel(canvas.layer, at[0], at[1], candidate[2], p,
          { size: 7.5, fill: p.muted });
      });
    }

    drawMapPoints(canvas, points.map(function (pt) {
      return Object.assign({ kind: 'diamond', size: 6.5 }, pt);
    }));
    return canvas.finish();
  }


  /* ------------------------------------------- sea, and the land beyond it */

  /* The land across the border that a window can see.
   *
   * The toolkit bundles no outline of Guinea or Liberia; the USGS layer
   * covers the whole clip window and has no polygon over the sea, so its
   * units are what tells land across the border from the Atlantic. The
   * Python engine takes the same rings in foreign_land_rings(). */
  function foreignLandFeatures(box) {
    var layer = (C.geoLayers() || {}).geology || {};
    var features = layer.features || [];
    if (!box) return features;
    return features.filter(function (feature) {
      return ringInBox(feature.geometry, box);
    });
  }

  /* Fill the frame as sea, then lay the country on top of it.
   *
   * Sierra Leone has 400 km of coast and this toolkit's busiest site is on
   * the Freetown peninsula, where half of every window is Atlantic. Drawn as
   * the page it read as blank paper, so the coastline looked like the edge
   * of the data rather than the edge of the land.
   *
   * Everything outside the national outline is filled, and across the land
   * border that is Guinea or Liberia, not ocean: those are painted in the
   * paper tone between the two, which is what sea_and_neighbours does in the
   * Python engine. The land across the border is passed in by the caller,
   * which knows what it is; without it everything outside the outline stays
   * sea. The country's own ground is painted over them again, so a foreign
   * polygon reaching across the border cannot tint the inside. */
  function seaAndNeighbours(canvas, outline, background, foreign) {
    if (!outline || !outline.length) return;
    canvas.layer.appendChild(svgEl('rect', {
      x: canvas.rect.x, y: canvas.rect.y,
      width: canvas.rect.w, height: canvas.rect.h, fill: MAP_SEA,
    }));
    (foreign || []).forEach(function (feature) {
      canvas.layer.appendChild(svgEl('path', {
        d: geometryPath(feature.geometry, canvas.project),
        fill: MAP_FOREIGN_LAND, stroke: 'none',
      }));
    });
    outline.forEach(function (feature) {
      canvas.layer.appendChild(svgEl('path', {
        d: geometryPath(feature.geometry, canvas.project),
        fill: background, stroke: 'none',
      }));
    });
  }

  /* One counter for every clip path this file mints, because an id that
   * repeats on a page silently makes two figures share one shape. */
  var clipSeq = 0;

  /* Everything beyond the national boundary, painted out as sea, with the
   * land across the border put back on top of it.
   *
   * The unit layers are clipped to a rectangle, not to the border, so a
   * polygon that straddles it runs on across Guinea and across the Atlantic;
   * this is what stops it, and it is the reason the key can promise that
   * every colour in it is findable inside the country. A rectangle with the
   * country rings punched out of it, even-odd filled - the compound path
   * _mask_outside_country builds in the Python engine - then the foreign
   * polygons clipped to that same shape, so nothing lands inside. */
  function maskOutsideCountry(canvas, outline, box) {
    if (!outline || !outline.length) return;
    var r = canvas.rect;
    var d = 'M' + r.x + ' ' + r.y + 'L' + (r.x + r.w) + ' ' + r.y +
      'L' + (r.x + r.w) + ' ' + (r.y + r.h) + 'L' + r.x + ' ' + (r.y + r.h) + 'Z';
    outline.forEach(function (feature) {
      d += ' ' + geometryPath(feature.geometry, canvas.project);
    });
    clipSeq += 1;
    var maskId = 'gwt-sea-' + clipSeq;
    var defs = svgEl('defs');
    defs.appendChild(svgEl('clipPath', { id: maskId }, [svgEl('path', {
      d: d, 'clip-rule': 'evenodd',
    })]));
    canvas.svg.insertBefore(defs, canvas.svg.firstChild);
    canvas.layer.appendChild(svgEl('path', {
      d: d, 'fill-rule': 'evenodd', fill: MAP_SEA, stroke: 'none',
    }));
    var neighbours = svgEl('g', { 'clip-path': 'url(#' + maskId + ')' });
    foreignLandFeatures(box).forEach(function (feature) {
      neighbours.appendChild(svgEl('path', {
        d: geometryPath(feature.geometry, canvas.project),
        fill: MAP_FOREIGN_LAND, stroke: 'none',
      }));
    });
    canvas.layer.appendChild(neighbours);
  }

  /* Everything the caller draws into the layer is held inside the neatline.
   * A chiefdom boundary or a geological contact that leaves the window runs
   * on over the title and the key otherwise, and the frame stops meaning
   * anything. */
  function clipToFrame(canvas) {
    clipSeq += 1;
    var clipId = 'gwt-clip-' + clipSeq;
    var defs = svgEl('defs');
    defs.appendChild(svgEl('clipPath', { id: clipId }, [svgEl('rect', {
      x: canvas.rect.x, y: canvas.rect.y,
      width: canvas.rect.w, height: canvas.rect.h,
    })]));
    canvas.svg.insertBefore(defs, canvas.svg.firstChild);
    canvas.layer.setAttribute('clip-path', 'url(#' + clipId + ')');
  }

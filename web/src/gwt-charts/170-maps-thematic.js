
  /* ---------------------------------------------------------- thematic map */

  /* The districts whose ground the Rokel River Group belt runs under, as
   * the crosswalk's regions name them. The Python engine tests
   * region_of(district) against the same two. */
  var ROKEL_BELT_REGIONS = ['coastal plain', 'north and centre'];

  /* The extent a whole-country map covers: the national outline's own bounds
   * with the margin the Python engine puts round them, 0.15 degrees east and
   * west and 0.12 north and south. Null when no outline was supplied. */
  function countryBox(outline) {
    if (!outline || !outline.length) return null;
    var b = featureBounds(outline);
    if (!isFinite(b.lonMin)) return null;
    return [b.lonMin - 0.15, b.latMin - 0.12, b.lonMax + 0.15, b.latMax + 0.12];
  }

  /* Is there ground in the window that the source layer draws no polygon
   * for?
   *
   * The bundled layers stop short of the coast in places - the Bullom shore
   * and the Sherbro estuaries most of all - and that ground is painted the
   * not-mapped tint. Only when it is actually on screen, though: a window
   * over the interior has no gaps in it, and a key entry for something not
   * on the map is its own small lie. The same 56 by 56 grid as
   * _unmapped_land_in_view in the Python engine, so the two engines agree
   * on whether the entry has been earned. */
  function unmappedLandInWindow(outline, units, box, samples) {
    if (!outline || !outline.length) return false;
    var n = samples || 56;
    for (var i = 0; i < n; i++) {
      var lon = box[0] + (box[2] - box[0]) * i / (n - 1);
      for (var j = 0; j < n; j++) {
        var lat = box[1] + (box[3] - box[1]) * j / (n - 1);
        if (!onLand(lon, lat, outline)) continue;
        var covered = units.some(function (unit) {
          return pointInFeature(lon, lat, unit.geometry);
        });
        if (!covered) return true;
      }
    }
    return false;
  }

  /* A categorical polygon layer - geology or aquifer productivity - clipped
   * to a window around the site when there is one.
   *
   * The layers carry their own published colours, so the map reads the same
   * way the source sheet does rather than being recoloured here.
   *
   * The legend names the units that cover ground inside the window that was
   * drawn, by the same three tests the Python engine uses in _ring_in_box.
   * Selecting by bounding box, which is the cheap first pass, would put a
   * unit in the legend whose only claim on the window is that its box
   * reaches across a country its polygon does not. */
  function thematicMap(spec) {
    var key = spec.key || 'unit';
    var window_ = spec.window || null;
    var outline = spec.outline || [];
    /* Units wholly outside Sierra Leone are dropped before anything else:
     * they are masked away when the map is drawn, so a key entry for one
     * is a colour the reader cannot find. */
    var all = (spec.features || []).filter(function (feature) {
      return meetsOutline(feature.geometry, outline);
    });
    if (!all.length) all = spec.features || [];

    var features = all, clip = null;
    if (window_) {
      var dLat = window_.radiusKm / 111.320;
      var dLon = window_.radiusKm /
        (111.320 * Math.max(Math.cos(window_.lat * Math.PI / 180), 1e-6));
      clip = [window_.lon - dLon, window_.lat - dLat,
        window_.lon + dLon, window_.lat + dLat];
      features = all.filter(function (feature) {
        var b = featureBounds([feature]);
        return isFinite(b.lonMin) && b.lonMin <= clip[2] && b.lonMax >= clip[0] &&
          b.latMin <= clip[3] && b.latMax >= clip[1];
      });
      if (!features.length) features = all;
    }

    /* The window itself sets the extent, so a 40 km map is a 40 km map even
     * when the polygon covering it runs the length of the country. With no
     * window, the country sets it: _plot_units_map frames on the outline's
     * own bounds with a fixed margin (regional.py:735-737), where taking the
     * extent from the unit polygons framed the national maps on ground that
     * runs into Guinea and Liberia and drew them at a wider scale than the
     * Python ones, down to ruling the graticule a step coarser. */
    var nationalBox = clip ? null : countryBox(outline);
    var boxExtent = function (bx) {
      return [{ geometry: { type: 'Polygon', coordinates: [[
        [bx[0], bx[1]], [bx[2], bx[1]], [bx[2], bx[3]], [bx[0], bx[3]],
      ]] } }];
    };
    var extent = clip ? boxExtent(clip)
      : (nationalBox ? boxExtent(nationalBox) : features);

    /* Which units are really in the window, and where each of them is.
     *
     * The key is scoped to the window that was drawn - the box the title and
     * the scale caveat describe - and not to the whole frame: the projection
     * letterboxes the window, so the frame shows a few kilometres of ground
     * beyond it either side, and a unit that reaches no further than that
     * margin is a colour the reader is sent hunting the map for. The Python
     * engine keys on the same box, its axes being the window exactly.
     *
     * Each polygon carries the district it is in rather than the site's,
     * because the crosswalk that names the rock is a regional table: scoped
     * by the site, the same Freetown Complex polygon came out as the
     * Freetown Layered Complex on one map and as "Paleozoic Igneous", the
     * age the crosswalk itself calls wrong, on another 100 km away. */
    var inWindow = (clip ? features.filter(function (feature) {
      return ringInBox(feature.geometry, clip);
    }) : features).map(function (feature) {
      return {
        feature: feature,
        district: unitDistrict(feature.geometry) || spec.district,
      };
    });

    /* Is any of the ground in the key's box unmapped? Settled here rather
     * than inside legendFor because the entry has a note to go with it, and
     * the note has to be written before mapCanvas measures the credit
     * block. Without a window the box is the national extent the Python
     * engine's axes carry - the country's own bounds with its margin round
     * them - because the frame is not laid out yet. */
    var keyBox = clip || countryBox(outline);
    var gapInView = !!keyBox && unmappedLandInWindow(
      outline, inWindow.map(function (placed) { return placed.feature; }),
      keyBox);

    function legendFor() {
      var seen = [];
      inWindow.forEach(function (placed) {
        var props = placed.feature.properties || {};
        var label = spec.nameLithology
          ? unitLabel(props, spec, placed.district)
          : String(props[key] || 'unclassified');
        if (!seen.some(function (s) { return s.label === label; })) {
          seen.push({ label: label, colour: unitColour(props, spec),
            era: eraRank(props), code: unitCode(props) });
        }
      });
      /* Era first and the source's own code after it, which is how the
       * Python engine orders a key: youngest at the top, the basement under
       * it, the non-geological classes last. The code is compared as Python
       * compares strings, by code point, rather than by the locale's
       * collation. */
      seen.sort(function (a, b) {
        if (a.era !== b.era) return a.era - b.era;
        return a.code < b.code ? -1 : (a.code > b.code ? 1 : 0);
      });
      var items = seen.slice();
      /* ground the source draws nothing for, named in the key rather than
       * left as an unexplained tint: beige with nothing beside it leaves a
       * reader guessing whether it is sea, a gap, or a unit whose colour
       * they have misread */
      if (gapInView) {
        items.push({ label: 'Not mapped at this scale',
          colour: MAP_NOT_MAPPED });
      }
      (spec.points || []).forEach(function (point) {
        if (!point.label) return;
        items.push({
          label: point.legend || point.label, kind: point.kind || 'diamond',
          colour: point.colour || palette().secondary,
        });
      });
      return items;
    }

    /* An age the source has wrong is said out loud rather than silently
     * corrected, so it has to be in the credit block before mapCanvas
     * measures it. Driven by the polygons the key will name, so a window
     * that does not reach the Freetown peninsula carries no note about it. */
    var notes = [];
    inWindow.forEach(function (placed) {
      var n = lithologyNote(placed.feature.properties || {}, spec, placed.district);
      if (n && notes.indexOf(n) < 0) notes.push(n);
    });
    /* the gap entry says what the tint is; this says why there is one, so a
     * reader is not left deciding for themselves whether the beige is sea,
     * a hole in the data, or a colour they have misread */
    if (gapInView) {
      notes.push('The not-mapped tint is land inside Sierra Leone that the ' +
        'source layer draws no polygon for; at this scale its coastal units ' +
        'stop short of the shore.');
    }
    /* The Rokel River Group belt sits inside the USGS Precambrian polygon,
     * which the 1:5,000,000 map does not separate from the granite around
     * it. The aquifer map beside this one shows the belt as fracture flow in
     * indurated sediments, and a reader comparing the two figures was given
     * nothing to reconcile them with. */
    if (spec.nameLithology &&
        ROKEL_BELT_REGIONS.indexOf(regionOf(spec.district)) >= 0 &&
        inWindow.some(function (placed) {
          return (placed.feature.properties || {}).glg === 'pCm';
        })) {
      notes.push('The Precambrian polygon here spans both the Leonean ' +
        'granite-gneiss and the Rokel River Group belt (Port Loko, Kambia, ' +
        'Moyamba, Tonkolili), which the 1:5,000,000 map does not separate; ' +
        'the aquifer map shows the belt as fracture flow in indurated ' +
        'sediments.');
    }
    /* the window that was drawn, not the one that was asked for: without a
     * position there is no window and the national map is the scale the
     * data was published at, which needs no apology */
    var caveat = scaleCaveat(window_ ? window_.radiusKm : null,
      spec.sourceScale, spec.publisherNote);
    if (caveat) notes.push(caveat);
    var credited = Object.assign({}, spec);
    if (notes.length) {
      credited.credit = [spec.credit, notes.join('  ')].filter(Boolean).join('  ');
    }

    var canvas = mapCanvas(credited, legendFor, extent);
    var p = canvas.palette;

    clipToFrame(canvas);

    /* Sea first, then the country, then the units on top of it. What is
     * left showing in the land tint is ground the source layer draws
     * nothing for, and the key names it. */
    seaAndNeighbours(canvas, outline, MAP_NOT_MAPPED);

    features.forEach(function (feature) {
      var props = feature.properties || {};
      canvas.layer.appendChild(svgEl('path', {
        d: geometryPath(feature.geometry, canvas.project),
        /* A hole is ground the unit does not cover - a dyke cutting the
         * country rock, a window of something else. evenodd leaves it open
         * whichever way the interior ring winds. */
        'fill-rule': 'evenodd',
        fill: unitColour(props, spec), 'fill-opacity': 0.85,
        stroke: p.surface, 'stroke-width': 0.5,
      }, [svgEl('title', { text: String(props[key] || 'unclassified') })]));
    });
    /* and the units stop at the border: what runs on past it is sea, or
     * Guinea and Liberia in the paper tone */
    maskOutsideCountry(canvas, outline, clip || canvas.project.visibleBox());
    (spec.context || []).forEach(function (feature) {
      canvas.layer.appendChild(svgEl('path', {
        d: geometryPath(feature.geometry, canvas.project), fill: 'none',
        stroke: p.axis, 'stroke-width': 0.8,
      }));
    });
    drawMapPoints(canvas, (spec.points || []).map(function (pt) {
      return Object.assign({ kind: 'diamond', size: 6.5 }, pt);
    }));
    return canvas.finish();
  }

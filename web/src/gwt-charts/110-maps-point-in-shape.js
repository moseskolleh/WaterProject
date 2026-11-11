
  /* --------------------------------------------------------- point in shape */

  /* Every exterior ring of a Polygon or MultiPolygon, holes dropped. Used
   * where only the outline matters and a hole cannot change the answer. */
  function ringsOf(geometry) {
    if (!geometry) return [];
    if (geometry.type === 'Polygon') return geometry.coordinates.slice(0, 1);
    if (geometry.type === 'MultiPolygon') {
      return geometry.coordinates.map(function (poly) { return poly[0]; });
    }
    return [];
  }

  function pointInRing(lon, lat, ring) {
    var inside = false;
    for (var i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      var xi = ring[i][0], yi = ring[i][1], xj = ring[j][0], yj = ring[j][1];
      if ((yi > lat) !== (yj > lat) &&
          lon < (xj - xi) * (lat - yi) / ((yj - yi) || 1e-12) + xi) {
        inside = !inside;
      }
    }
    return inside;
  }

  /* Does this polygon cover any ground inside the country outline?
   *
   * The bundled layers are clipped to a rectangle, not to the border, so
   * they carry polygons lying wholly in Guinea or Liberia - the Ordovician
   * and Silurian of the Bove Basin are entirely across the northern border.
   * Listing them in the key sends a reader hunting the map for a colour
   * that is not on it. Cheap and symmetric, the same test the Python engine
   * uses in mapping/regional.py as _ring_meets_country: a unit vertex
   * inside the country, or a border vertex inside the unit. */
  function meetsOutline(geometry, outline) {
    if (!outline || !outline.length) return true;
    var rings = ringsOf(geometry);
    for (var o = 0; o < outline.length; o++) {
      var border = ringsOf(outline[o].geometry);
      for (var b = 0; b < border.length; b++) {
        for (var i = 0; i < rings.length; i++) {
          for (var j = 0; j < rings[i].length; j++) {
            if (pointInRing(rings[i][j][0], rings[i][j][1], border[b])) return true;
          }
        }
        for (var k = 0; k < border[b].length; k++) {
          if (pointInFeature(border[b][k][0], border[b][k][1], geometry)) return true;
        }
      }
    }
    return false;
  }

  function onLand(lon, lat, outline) {
    if (!outline || !outline.length) return true;
    for (var i = 0; i < outline.length; i++) {
      if (pointInFeature(lon, lat, outline[i].geometry)) return true;
    }
    return false;
  }

  function pointInFeature(lon, lat, geometry) {
    if (!geometry) return false;
    function inPolygon(rings) {
      if (!rings.length || !pointInRing(lon, lat, rings[0])) return false;
      for (var h = 1; h < rings.length; h++) {
        if (pointInRing(lon, lat, rings[h])) return false;   /* in a hole */
      }
      return true;
    }
    if (geometry.type === 'Polygon') return inPolygon(geometry.coordinates);
    if (geometry.type === 'MultiPolygon') {
      return geometry.coordinates.some(inPolygon);
    }
    return false;
  }

  /* Does this polygon actually reach into the window?
   *
   * The same three tests as _ring_in_box in the Python engine, and for the
   * same reason: two rectangles can overlap while the shapes inside them do
   * not touch, and a key built on the bounding boxes alone named a
   * consolidated sedimentary aquifer on a map of the Freetown peninsula
   * because that unit's box reaches across a country the polygon does not.
   * So: a vertex inside the window, a window corner inside the ring, or an
   * edge of one crossing an edge of the other. Those three are the whole of
   * it. The first is answered by the same pass that measures the ring, and
   * the extents reject the rest of the layer before the expensive tests run:
   * a national geology layer is 92 polygons and the reports draw several
   * figures each. */
  function ringInBox(geometry, box) {
    return ringsOf(geometry).some(function (ring) {
      return ringReachesBox(ring, box);
    });
  }

  function ringReachesBox(ring, box) {
    var lonMin = Infinity, lonMax = -Infinity, latMin = Infinity, latMax = -Infinity;
    for (var i = 0; i < ring.length; i++) {
      if (ring[i][0] < lonMin) lonMin = ring[i][0];
      if (ring[i][0] > lonMax) lonMax = ring[i][0];
      if (ring[i][1] < latMin) latMin = ring[i][1];
      if (ring[i][1] > latMax) latMax = ring[i][1];
      if (ring[i][0] >= box[0] && ring[i][0] <= box[2] &&
          ring[i][1] >= box[1] && ring[i][1] <= box[3]) return true;
    }
    if (!(lonMax >= box[0] && lonMin <= box[2] &&
          latMax >= box[1] && latMin <= box[3])) return false;
    var corners = [[box[0], box[1]], [box[2], box[1]],
      [box[2], box[3]], [box[0], box[3]]];
    for (var c = 0; c < corners.length; c++) {
      if (pointInRing(corners[c][0], corners[c][1], ring)) return true;
    }
    return ringCrossesBoxEdge(ring, box);
  }

  /* The remaining case: a long thin polygon - a dyke, a river, a coastal
   * strip - slicing clean through the window without a vertex landing in it
   * and without swallowing a corner. */
  function ringCrossesBoxEdge(ring, box) {
    var sides = [
      [[box[0], box[1]], [box[2], box[1]]],
      [[box[2], box[1]], [box[2], box[3]]],
      [[box[2], box[3]], [box[0], box[3]]],
      [[box[0], box[3]], [box[0], box[1]]],
    ];
    function side(a, b, c) {
      return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
    }
    for (var i = 0; i < ring.length - 1; i++) {
      for (var s = 0; s < sides.length; s++) {
        var q1 = sides[s][0], q2 = sides[s][1];
        var d1 = side(q1, q2, ring[i]), d2 = side(q1, q2, ring[i + 1]);
        var d3 = side(ring[i], ring[i + 1], q1);
        var d4 = side(ring[i], ring[i + 1], q2);
        if (d1 * d2 < 0 && d3 * d4 < 0) return true;
      }
    }
    return false;
  }

  /* Shoelace area, unsigned: which part of a chiefdom is the one worth
   * writing the name on when several are in view. */
  function ringArea(ring) {
    var sum = 0;
    for (var i = 0; i < ring.length - 1; i++) {
      sum += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1];
    }
    return Math.abs(sum / 2);
  }

  /* Where to write an area's name, given only the parts of it in view.
   *
   * The centroid of the largest ring is the right answer for a whole country
   * and the wrong one for a chiefdom clipped by the window: it lands outside
   * the frame, and the name is either not drawn or drawn on the edge
   * pointing at nothing. The mean of the vertices that are actually inside
   * the window is inside the window by construction. _label_spot in the
   * Python engine. */
  function labelSpot(rings, box) {
    var lon = 0, lat = 0, n = 0;
    rings.forEach(function (ring) {
      ring.forEach(function (v) {
        if (v[0] > box[0] && v[0] < box[2] && v[1] > box[1] && v[1] < box[3]) {
          lon += v[0]; lat += v[1]; n += 1;
        }
      });
    });
    return n < 3 ? null : [lon / n, lat / n];
  }


  /* ============================================= Terrain analysis: assembly
   * groundwater/mapping/terrain_analysis.py's analysis block: the routing
   * and the surface kernels run together on one window (analyseTerrain),
   * the drainage lines traced from the routing and cut to the square shown
   * (drainageLinks), the summary of that square, the captions
   * (terrainCaptions) and the drainage lines' GeoJSON (drainageGeoJson).
   *
   * Every step is Python's, in Python's order: the same layers taken in
   * the same order, each float sum added left to right from 0, the lines
   * numbered and visited in grid order, the captions chosen by the same
   * tests and returned under the same keys in the same order. Links,
   * parts, the summary and the captions keep Python's snake_case field
   * names, because they are data both apps print and the parity suite
   * compares as JSON; the analysis object itself takes this file's
   * camelCase. Counts and areas are whole numbers in Float64Array, exact
   * below 2^53 in any order, as in the routing above.
   *
   * The worker hands the page the core (terrainCore) and display copies of
   * the layers (terrainDisplayLayers), and the page re-traces the lines
   * from the core alone when the threshold changes: drainageLinks is the
   * one function both apps trace with, on the same inputs. Everything is
   * synchronous and DOM-free, for the worker and the Node sandboxes
   * alike; hot loops call no global, which a Node vm looks up through its
   * context at every use. */

  /** @typedef {{lons: ArrayLike<number>, lats: ArrayLike<number>, z: ArrayLike<number>, rows: number,
   *   cols: number, shown?: ArrayLike<number>|null, assumedSea?: ArrayLike<number>|null,
   *   sourceId?: string, seaClean?: boolean, label?: string}} TerrainGrid  a window of heights, south
   *   row first, as readElevationWindow's read holds it (its other fields are not read here) */
  /** @typedef {{rows: number, cols: number, shown: number[], lons: Float64Array, lats: Float64Array,
   *   dx: Float64Array, dy: Float64Array, dg: Float64Array, count: Float64Array, areaUnits: Float64Array,
   *   cls: Uint8Array, code: Uint8Array, flag: Uint8Array, raised: Uint8Array,
   *   flatRouted: Uint8Array}} TerrainCore  what drainageLinks traces from: terrain_analysis.TerrainCore */
  /** @typedef {{id: number, start: number, vertices: Array<[number, number]>, cells: number,
   *   outlet: string, downstream: number, strahler: number, area_units: number, length_m: number,
   *   edge_contaminated: boolean, filled_cells: number, flat_routed_cells: number}} DrainageLink
   *   one drainage line over the analysed square: terrain_analysis.DrainageLink */
  /** @typedef {{id: number, part: number, vertices: Array<[number, number]>, stretch_flat: boolean[],
   *   outlet: string, strahler: number, downstream: number, area_units: number, length_m: number,
   *   edge_contaminated: boolean, filled_cells: number, flat_routed_cells: number}} DrainagePart
   *   a drainage line's piece inside the square shown: terrain_analysis.DrainagePart */
  /** @typedef {{grid: TerrainGrid, metric: {dx: Float64Array, dy: Float64Array, dg: Float64Array,
   *   auRow: Float64Array}, core: TerrainCore, filled: Float64Array, fillDepth: Float64Array|Float32Array,
   *   unresolved: number, stream: Uint8Array, links: DrainageLink[], parts: DrainagePart[],
   *   p: Float64Array, q: Float64Array, tanb: Float64Array|Float32Array,
   *   hillshades: Array<Float64Array|Float32Array>, hillshadeMulti: Float64Array|Float32Array,
   *   twiArg: Float64Array, twi: Float64Array|Float32Array, profile: Float64Array|Float32Array,
   *   tangential: Float64Array|Float32Array, kCells: number, floored: number, zeroFill: number,
   *   summary: Rec, settings: Rec}} TerrainAnalysis  everything worked out from one window:
   *   terrain_analysis.TerrainAnalysis */

  /* The drainage threshold in whole 0.01 m^2 units, rounded half up: 0.5
   * km^2 is 5e7 units, about 532 cells at 8.5 degrees north and 1
   * arc-second. Areas are compared as whole numbers, so a cell is a stream
   * cell in both engines or in neither. Both refuse an area that is not a
   * finite number of square kilometres, 0 or more, small enough to count
   * in 0.01 m^2 units: past about 1.8e300 km^2 the count overflows to
   * Infinity, which Python cannot floor to a whole number. */
  function assemblyThreshold(areaKm2) {
    var area = typeof areaKm2 === 'number' ? areaKm2 : NaN;
    var units = area * 1e8 + 0.5;
    if (!(area >= 0 && units < Infinity)) {
      throw new Error('the drainage area must be a number of square kilometres, not ' + areaKm2);
    }
    return Math.floor(units);
  }

  /* The first index of the ascending `turns` whose value is above `value`
   * (`orEqual` false) or at or above it (true): Python's bisect_right and
   * bisect_left. */
  function assemblyBisect(turns, value, orEqual) {
    var lo = 0, hi = turns.length;
    while (lo < hi) {
      var mid = (lo + hi) >>> 1;
      if (turns[mid] < value || (!orEqual && turns[mid] === value)) lo = mid + 1;
      else hi = mid;
    }
    return lo;
  }

  /* The positions a to b - 1 of a line kept as vertices: both ends, and
   * every position between them in `turns` (where the line turns or
   * changes how it was routed). One position is one vertex. `turns` is in
   * ascending order, so the turns inside are found by two binary searches
   * rather than a scan of the whole list: a line that leaves the square
   * shown and comes back is cut into many parts, and a scan per part
   * would cost the parts times the turns. */
  function assemblyVertexPositions(turns, a, b) {
    if (b - a === 1) return [a];
    var out = [a];
    var hi = assemblyBisect(turns, b - 1, true);
    for (var t = assemblyBisect(turns, a, false); t < hi; t++) out.push(turns[t]);
    out.push(b - 1);
    return out;
  }

  /**
   * The drainage lines where more than `areaKm2` drains, over the analysed
   * square, and their parts in the square shown:
   * terrain_analysis.drainage_links. A stream cell is a land cell with at
   * least the threshold's area. A line starts at every stream cell no
   * other stream cell drains to (a headwater) and at every one that two or
   * more drain to (a confluence), numbered in grid order, and follows the
   * directions until it meets the next confluence, which starts another
   * line, or leaves the land: into the sea, which it runs into, or out of
   * the analysis at the edge or at a void. Strahler orders are worked out
   * upstream first: a line no other line joins is of order 1, and a line
   * is one higher than the highest that joins it only where two or more
   * of that order meet.
   *
   * Each line is then cut to the square shown, so that what is drawn and
   * exported ends at the edge of the map rather than in the margin, while
   * its area, flag and order stay those worked out over the whole analysed
   * square; a piece of a single position is dropped and takes no number.
   * Only whole numbers and comparisons decide the lines, and lengths are
   * added in order along them, so the page, re-tracing from the core its
   * worker handed over (structuredClone included), draws Python's lines
   * to the bit. Vertices are [row, column] of the analysed grid.
   * @param {TerrainCore} core what terrainCore gives
   * @param {number} areaKm2 the drainage threshold, km^2 (terrain.drainage_area_km2)
   * @returns {{links: DrainageLink[], parts: DrainagePart[]}} the links in grid order of their first
   *   cell, the parts by (id, part)
   */
  function drainageLinks(core, areaKm2) {
    var rows = core.rows, cols = core.cols, n = rows * cols;
    var r0 = core.shown[0], r1 = core.shown[1], c0 = core.shown[2], c1 = core.shown[3];
    var threshold = assemblyThreshold(areaKm2);
    var cls = core.cls, code = core.code, area = core.areaUnits, count = core.count;
    var flag = core.flag, raised = core.raised, flatRouted = core.flatRouted;
    [cls, code, area, count, flag, raised, flatRouted].forEach(function (layer) {
      if (layer.length !== n) {
        throw new Error('a core of ' + rows + ' by ' + cols + ' cells holds a layer of ' + layer.length);
      }
    });
    /** @type {DrainageLink[]} */
    var links = [];
    /** @type {DrainagePart[]} */
    var parts = [];
    /* the stream cells in grid order, and each one's place among them */
    var place = new Int32Array(n).fill(-1), m = 0, i, p;
    for (i = 0; i < n; i++) {
      if (cls[i] === ROUTE_LAND && area[i] >= threshold) place[i] = m++;
    }
    if (!m) return { links: links, parts: parts };
    var cells = new Int32Array(m);
    for (i = 0; i < n; i++) if (place[i] >= 0) cells[place[i]] = i;

    /* Every stream cell's neighbour along its direction. A stream cell's
     * area only grows downstream, so a land neighbour is a stream cell too;
     * anything else means the core's layers do not belong together. A code
     * that is no direction steps as east does, as Python's indexing has it,
     * though only a flowing direction is ever followed. */
    var down = new Int32Array(m), feeds = new Int32Array(m), dist = new Float64Array(m);
    var rowOf = new Int32Array(m), colOf = new Int32Array(m), nextRow = new Int32Array(m);
    var nextCol = new Int32Array(m), edge = new Uint8Array(m), outOfGrid = false, belowThreshold = false;
    for (p = 0; p < m; p++) {
      i = cells[p];
      var r = (i / cols) | 0, c = i - r * cols, k = ROUTE_K_OF_CODE[code[i]], kk = k >= 0 ? k : 0;
      rowOf[p] = r;
      colOf[p] = c;
      edge[p] = r === 0 || r === rows - 1 || c === 0 || c === cols - 1 ? 1 : 0;
      nextRow[p] = r + ROUTE_DR[kk];
      nextCol[p] = c + ROUTE_DC[kk];
      down[p] = -1;
      if (k < 0) continue;
      if (nextRow[p] < 0 || nextRow[p] >= rows || nextCol[p] < 0 || nextCol[p] >= cols) {
        outOfGrid = true;
        continue;
      }
      dist[p] = k >= 4 ? core.dg[r] : k % 2 ? core.dy[r] : core.dx[r];
      var j = nextRow[p] * cols + nextCol[p];
      if (cls[j] !== ROUTE_LAND) continue;
      if (place[j] < 0) {
        belowThreshold = true;
        continue;
      }
      down[p] = place[j];
    }
    /* refused in Python's order: a direction off the grid first */
    if (outOfGrid) throw new Error('a direction in the core points out of the grid');
    if (belowThreshold) throw new Error('a stream cell drains to land below the threshold; the core\'s layers disagree');
    for (p = 0; p < m; p++) if (down[p] >= 0) feeds[down[p]] += 1;
    /** @type {number[]} */
    var starts = [];
    var linkOf = new Int32Array(m).fill(-1);
    for (p = 0; p < m; p++) {
      if (feeds[p] === 0 || feeds[p] >= 2) {
        linkOf[p] = starts.length;
        starts.push(p);
      }
    }

    /* each line: its own cells (by place), how it ends, the line it joins
     * and the position it runs into, where it runs into one */
    var traced = starts.map(function (s) {
      var own = [s], cur = s, joins = -1, outlet = '';
      /** @type {[number, number]|null} */
      var end = null;
      for (;;) {
        var d = down[cur];
        if (d >= 0) {
          if (feeds[d] >= 2) {
            outlet = 'confluence';
            joins = linkOf[d];
            end = [rowOf[d], colOf[d]];
            break;
          }
          own.push(d);
          cur = d;
        } else if (code[cells[cur]] === 255) {
          outlet = edge[cur] ? 'edge' : 'void';
          break;
        } else if (code[cells[cur]] === 0) {
          outlet = 'sink';          // a flat left without a direction: never expected
          break;
        } else {
          outlet = 'sea';
          end = [nextRow[cur], nextCol[cur]];
          break;
        }
      }
      return { own: own, outlet: outlet, joins: joins, end: end };
    });

    /* Strahler orders, upstream first: a line's first cell gathers more
     * cells than any cell upstream of it, so ordering by that count, then
     * by the cell, puts every line after the lines that join it. */
    var joining = starts.map(function () { return /** @type {number[]} */ ([]); });
    traced.forEach(function (line, t) { if (line.joins >= 0) joining[line.joins].push(t); });
    var order = starts.map(function () { return 0; });
    var byCount = starts.map(function (s, t) { return t; });
    byCount.sort(function (a, b) {
      var ca = count[cells[starts[a]]], cb = count[cells[starts[b]]];
      return ca !== cb ? (ca < cb ? -1 : 1) : starts[a] - starts[b];
    });
    byCount.forEach(function (t) {
      var incoming = joining[t];
      if (!incoming.length) {
        order[t] = 1;
        return;
      }
      var top = 0, tops = 0;
      incoming.forEach(function (u) { if (order[u] > top) top = order[u]; });
      incoming.forEach(function (u) { if (order[u] === top) tops += 1; });
      order[t] = tops >= 2 ? top + 1 : top;
    });

    var flat = function (q) { return !!flatRouted[cells[q]]; };
    var lengthOf = function (own, a, b) {
      /* the steps of own[a] to own[b - 1], added left to right from 0 */
      var total = 0.0;
      for (var x = a; x < b; x++) total += dist[own[x]];
      return total;
    };
    var counted = function (layer, own, a, b) {
      var total = 0;
      for (var x = a; x < b; x++) if (layer[cells[own[x]]]) total += 1;
      return total;
    };
    traced.forEach(function (line, t) {
      var own = line.own, places = own.map(function (q) {
        return /** @type {[number, number]} */ ([rowOf[q], colOf[q]]);
      });
      if (line.end !== null) places.push(line.end);
      var size = places.length, x;
      /* where the line turns or changes how it was routed */
      var turns = [];
      for (x = 1; x < own.length; x++) {
        if (code[cells[own[x]]] !== code[cells[own[x - 1]]] || flat(own[x]) !== flat(own[x - 1])) turns.push(x);
      }
      var last = cells[own[own.length - 1]];
      links.push({
        id: t, start: cells[own[0]],
        vertices: assemblyVertexPositions(turns, 0, size).map(function (v) { return places[v]; }),
        cells: own.length, outlet: line.outlet, downstream: line.joins, strahler: order[t],
        area_units: area[last], length_m: lengthOf(own, 0, size - 1), edge_contaminated: !!flag[last],
        filled_cells: counted(raised, own, 0, own.length), flat_routed_cells: counted(flatRouted, own, 0, own.length),
      });

      /* the runs of positions inside the square shown */
      var piece = 0, at = 0;
      var inside = places.map(function (rc) { return rc[0] >= r0 && rc[0] < r1 && rc[1] >= c0 && rc[1] < c1; });
      while (at < size) {
        if (!inside[at]) {
          at += 1;
          continue;
        }
        var a = at;
        while (at < size && inside[at]) at += 1;
        if (at - a < 2) continue;
        var mineEnd = Math.min(at, own.length), mine = cells[own[mineEnd - 1]];
        var kept = assemblyVertexPositions(turns, a, at);
        parts.push({
          id: t, part: piece, vertices: kept.map(function (v) { return places[v]; }),
          stretch_flat: kept.slice(0, -1).map(function (v) { return flat(own[v]); }),
          outlet: at === size ? line.outlet : 'beyond_view', strahler: order[t], downstream: line.joins,
          area_units: area[mine], length_m: lengthOf(own, a, at - 1), edge_contaminated: !!flag[mine],
          filled_cells: counted(raised, own, a, mineEnd), flat_routed_cells: counted(flatRouted, own, a, mineEnd),
        });
        piece += 1;
      }
    });
    return { links: links, parts: parts };
  }

  /**
   * The summary's counts of drainage-line cells in the square shown at a
   * threshold, as terrain_analysis.analyse_terrain counts them: the land
   * cells (class 1) with at least the threshold's area, the threshold in
   * whole 0.01 m^2 units as drainageLinks takes it, those of them routed
   * across a flat or a filled hollow, and those flagged for edge
   * contamination; each share is of the line cells, 0 of none.
   * analyseTerrain counts its summary with this, and the page counts again
   * with it, from the core alone, when the threshold changes.
   * @param {TerrainCore} core what terrainCore gives
   * @param {number} areaKm2 the drainage threshold, km^2 (terrain.drainage_area_km2)
   * @returns {{flat_routed_stream: number, stream: number, contaminated_stream: number,
   *   flat_routed_lines_pct: number, contaminated_pct: number, threshold_units: number}}
   */
  function streamCounts(core, areaKm2) {
    var threshold = assemblyThreshold(areaKm2);
    var cls = core.cls, area = core.areaUnits, flatRouted = core.flatRouted, flag = core.flag;
    var cols = core.cols, shown = core.shown, stream = 0, flat = 0, flagged = 0;
    for (var r = shown[0]; r < shown[1]; r++) {
      for (var i = r * cols + shown[2]; i < r * cols + shown[3]; i++) {
        if (cls[i] !== ROUTE_LAND || area[i] < threshold) continue;
        stream += 1;
        flat += flatRouted[i];
        flagged += flag[i] ? 1 : 0;
      }
    }
    return {
      flat_routed_stream: flat, stream: stream, contaminated_stream: flagged,
      flat_routed_lines_pct: assemblyShare(flat, stream), contaminated_pct: assemblyShare(flagged, stream),
      threshold_units: threshold,
    };
  }

  /* A string as Python's json.dumps writes it with ensure_ascii (spec
   * 3.10): the quote and the backslash escaped, \b \f \n \r \t by name,
   * any other code unit below 0x20 and every one from 0x7F up as \uXXXX in
   * lowercase hex, each half of a pair on its own as Python writes a
   * character beyond the BMP. A file or place name in any script then
   * gives the same bytes in both engines. */
  var JSON_NAMED = /** @type {Record<string, string>} */ (
    { '"': '\\"', '\\': '\\\\', '\b': '\\b', '\f': '\\f', '\n': '\\n', '\r': '\\r', '\t': '\\t' });
  function jsonAscii(s) {
    var out = '"';
    for (var i = 0; i < s.length; i++) {
      var ch = s.charAt(i), unit = s.charCodeAt(i);
      if (own(JSON_NAMED, ch)) out += JSON_NAMED[ch];
      else if (unit < 0x20 || unit >= 0x7f) out += '\\u' + ('000' + unit.toString(16)).slice(-4);
      else out += ch;
    }
    return out + '"';
  }

  /* The GeoJSON's description, which terrainCaptions gives again as
   * geojson_description: terrain_analysis._geojson_description. What the
   * lines are and are not, and, when the source does not say it writes the
   * sea as 0 m and the analysed window holds sea, why the lines ending
   * there are flagged. */
  function geojsonDescription(label, area, radius, where, margin, depth, surface, seaUnstated, level) {
    var text = phrase('terrain.geojson_description', { label: label, area: area, radius: radius, where: where,
      margin: margin, depth: depth, surface: surface });
    if (seaUnstated) text += ' ' + phrase('terrain.geojson_sea_unstated', { level: level });
    return text;
  }

  /**
   * The drainage lines shown, as GeoJSON text written by hand, without
   * whitespace and in a fixed key order, so that both engines write the
   * same bytes: terrain_analysis.drainage_geojson. The description says
   * what the lines are and are not, in the catalogue's words, and why
   * lines ending in sea are flagged when the source may write a fill
   * value as sea; the notice is written only for a set holding a
   * Copernicus file, as its licence asks. Each feature's link number is
   * the property "link", never "id": a line cut into parts repeats it,
   * and GDAL takes an integer "id" property for the feature id, which it
   * then renumbers on conversion. Coordinates have six decimals (about 0.1
   * m) and areas six in km^2, lengths one in metres, all rounded as Python
   * rounds (pyFixed); the threshold, radius and margin are written as
   * Python's "%g" (formatG). Parts are written in the order given, which
   * drainageLinks makes (id, part).
   * @param {TerrainCore} core the core the parts were traced from (for its cell centres)
   * @param {DrainagePart[]} parts what drainageLinks gives
   * @param {{label: string, figure_credit: string, notice?: string|null, surface: string, area: number,
   *   radius: number, margin: number, centre: {lon: number, lat: number, label: string},
   *   fill_note_m: number, sea_clean: boolean, sea_cells: number, sea_level_m: number}} meta Python's
   *   meta keys: what the files are (label); the credit line a figure of the set carries, as the read's
   *   figureCredit gives it; the Copernicus notice or null; what the heights are heights of; the
   *   drainage threshold (km^2); the radius and margin (km); the window's centre; the fill depth
   *   filled_cells counts from (m); and the source's sea rule, the sea cells of the analysed window
   *   (assumed sea included) and the sea level (m)
   * @returns {string}
   */
  function drainageGeoJson(core, parts, meta) {
    var centre = meta.centre;
    var description = geojsonDescription(meta.label, meta.area, meta.radius, centre.label, meta.margin,
      meta.fill_note_m, meta.surface, !meta.sea_clean && Number(meta.sea_cells) > 0, meta.sea_level_m);
    var out = ['{"type":"FeatureCollection","description":', jsonAscii(description),
      ',"attribution":', jsonAscii(String(meta.figure_credit))];
    if (meta.notice) out.push(',"notice":', jsonAscii(String(meta.notice)));
    out.push(',"drainage_area_km2":' + formatG(Number(meta.area)), ',"radius_km":' + formatG(Number(meta.radius)),
      ',"margin_km":' + formatG(Number(meta.margin)),
      ',"centre":[' + pyFixed(Number(centre.lon), 6) + ',' + pyFixed(Number(centre.lat), 6) + '],"features":[');
    var lons = core.lons, lats = core.lats;
    parts.forEach(function (part, t) {
      var line = part.vertices.map(function (v) {
        return '[' + pyFixed(lons[v[1]], 6) + ',' + pyFixed(lats[v[0]], 6) + ']';
      }).join(',');
      out.push((t ? ',' : '') +
        '{"type":"Feature","properties":{"link":' + String(part.id) + ',"part":' + String(part.part) +
        ',"strahler":' + String(part.strahler) + ',"outlet":' + jsonAscii(part.outlet) +
        ',"area_km2":' + pyFixed(part.area_units / 1e8, 6) + ',"length_m":' + pyFixed(part.length_m, 1) +
        ',"edge_contaminated":' + (part.edge_contaminated ? 'true' : 'false') +
        ',"filled_cells":' + String(part.filled_cells) + ',"flat_routed_cells":' + String(part.flat_routed_cells) +
        ',"downstream":' + String(part.downstream) +
        '},"geometry":{"type":"LineString","coordinates":[' + line + ']}}');
    });
    out.push(']}');
    return out.join('');
  }

  /* The square shown as rows r0 to r1 and columns c0 to c1 (half-open),
   * the whole grid when none is given; refused unless it lies inside the
   * grid. Whole numbers are taken as Python's int() takes them. */
  function assemblySquare(shown, rows, cols) {
    if (shown === undefined || shown === null) return [0, rows, 0, cols];
    var r0 = Math.trunc(Number(shown[0])), r1 = Math.trunc(Number(shown[1]));
    var c0 = Math.trunc(Number(shown[2])), c1 = Math.trunc(Number(shown[3]));
    if (!(r0 >= 0 && r0 < r1 && r1 <= rows && c0 >= 0 && c0 < c1 && c1 <= cols)) {
      throw new Error('the square shown, rows ' + r0 + ':' + r1 + ' and columns ' + c0 + ':' + c1 +
        ', is not inside the ' + rows + ' by ' + cols + ' grid');
    }
    return [r0, r1, c0, c1];
  }

  /* count as a percentage of total, written as Python writes it; 0 of
   * nothing is 0 */
  function assemblyShare(count, total) {
    return total ? (100.0 * count) / total : 0.0;
  }

  /**
   * Analyse a window of an elevation model: where water would run, the
   * drainage lines, the shading, the wetness index and the curvature:
   * terrain_analysis.analyse_terrain. The grid's assumedSea marks a
   * missing tile taken as open sea, which has no height, and its seaClean
   * the source's sea rule. `shown` is the square shown, as rows [r0, r1)
   * and columns [c0, c1) of the grid; when left out the grid's own shown
   * square is taken (readElevationWindow gives one), and the whole grid
   * when it has none, as Python's shown=None. The window beyond it is the
   * margin: analysed, so that the edge of the analysis does not bend the
   * lines, while the lines are cut and the summary counted where the map
   * ends. `progress(fraction, label)`, when given, hears each stage start,
   * in the catalogue's words, at Python's fractions.
   *
   * Every count, threshold, drainage line and display limit is taken in
   * float64 or from whole numbers. With precision 'float32' (the default,
   * as in Python) the layers that are only drawn - the slope, the
   * hillshades, the wetness index, the curvatures and the fill depth - are
   * then narrowed to Float32Array, each as soon as nothing more is read
   * from it, which halves what they hold at the cap on cells; p, q, twiArg,
   * the filled surface, the core and the lines keep full precision. The
   * parity suite runs 'float64', where every layer is Python's to the bit
   * and the wetness index to 1e-12.
   * @param {TerrainGrid} grid the window: heights south row first, its axes, the assumed sea and the
   *   source's sea rule
   * @param {Rec|null} [cfg] the project's configuration (or a part of it, as withConfig takes)
   * @param {((fraction: number, label: string) => void)|null} [progress]
   * @param {string|null} [precision] 'float32' (the default) or 'float64'
   * @param {ArrayLike<number>|null} [shown] the square shown as [r0, r1, c0, c1]
   * @returns {TerrainAnalysis}
   */
  function analyseTerrain(grid, cfg, progress, precision, shown) {
    var settings = withConfig(cfg).terrain;
    var mode = precision === undefined || precision === null ? 'float32' : precision;
    if (mode !== 'float32' && mode !== 'float64') {
      throw new Error("precision must be 'float32' or 'float64', not " + JSON.stringify(precision));
    }
    var narrow = mode === 'float32';
    var keep = function (layer) { return narrow ? new Float32Array(layer) : layer; };
    /* each stage is announced with the share of the whole gone before it,
     * as measured at the default window (the fill takes about a third) */
    var stage = function (fraction, label) { if (progress) progress(fraction, label); };

    var rows = grid.rows, cols = grid.cols, n = rows * cols, i, r;
    if (!(Number.isInteger(rows) && Number.isInteger(cols) && rows >= 0 && cols >= 0) ||
        grid.z.length !== n || grid.lats.length !== rows || grid.lons.length !== cols) {
      throw new Error('the elevation grid holds ' + grid.z.length + ' heights, but ' + grid.lats.length +
        ' latitudes and ' + grid.lons.length + ' longitudes were given');
    }
    var z = new Float64Array(n), given = grid.z;
    for (i = 0; i < n; i++) z[i] = given[i] + 0.0;          // -0 becomes +0
    var square = assemblySquare(shown === undefined || shown === null ? grid.shown : shown, rows, cols);
    var r0 = square[0], r1 = square[1], c0 = square[2], c1 = square[3];
    var assumed = grid.assumedSea || null;
    var lons = Float64Array.from(grid.lons), lats = Float64Array.from(grid.lats);
    var metric = rowMetric(lons, lats);
    /* The routing, the wetness index and the curvature take every cell
     * size as a distance. An axis that descends makes the sizes negative,
     * which turns every drop round and sends water uphill into loops, and
     * one with no step makes them 0, so both are refused here, as in
     * Python; rowMetric itself takes them, because the shading is right on
     * either order. NaN fails the test as well. */
    for (r = 0; r < rows; r++) {
      if (!(metric.dx[r] > 0 && metric.dy[r] > 0)) throw new Error(phrase('terrain.axes_descend'));
    }
    var threshold = assemblyThreshold(settings.drainage_area_km2);

    stage(0.0, phrase('terrain.stage_classes'));
    var classes = classifyCells(z, rows, cols, settings.sea_level_m, assumed, settings.sea_straight_edge_cells);
    var cls = classes.cls, zt = classes.zt;
    /* What each cell of the square shown is. Together they count every
     * cell once: land, sea with a height, assumed sea, a zero-filled gap,
     * or no height in the window at all (uncovered), which is either no
     * value (voids) or an infinite one (implausible). */
    var land = 0, sea = 0, assumedShown = 0, uncovered = 0, implausible = 0, zeroFill = 0;
    for (r = r0; r < r1; r++) {
      for (i = r * cols + c0; i < r * cols + c1; i++) {
        var marked = !!(assumed && assumed[i]), v = z[i];
        if (cls[i] === ROUTE_LAND) land += 1;
        else if (cls[i] === ROUTE_SEA) {
          if (marked) assumedShown += 1;
          else sea += 1;
        }
        if (!marked && v - v !== 0) {
          uncovered += 1;
          if (v === v) implausible += 1;
        }
        if (classes.zeroFill[i]) zeroFill += 1;
      }
    }
    var cells = (r1 - r0) * (c1 - c0);
    /** @type {Rec} */
    var summary = { cells: cells, land: land, sea: sea, assumed_sea: assumedShown, voids: uncovered - implausible,
      uncovered: uncovered, implausible: implausible, zero_fill: zeroFill };

    stage(0.15, phrase('terrain.stage_fill'));
    var filled = fillDepressions(zt, cls, classes.seed, rows, cols);
    stage(0.45, phrase('terrain.stage_flow'));
    var codeD8 = flowDirections(zt, filled, cls, classes.seed, rows, cols, metric, settings.sea_level_m);
    stage(0.5, phrase('terrain.stage_flats'));
    var flats = resolveFlats(filled, cls, codeD8, rows, cols);
    var fillDepth = new Float64Array(n), raised = new Uint8Array(n), flatRouted = new Uint8Array(n);
    var note = settings.fill_note_m;
    for (i = 0; i < n; i++) {
      if (cls[i] !== ROUTE_LAND) {
        fillDepth[i] = NaN;
        continue;
      }
      var depth = filled[i] - zt[i];
      fillDepth[i] = depth;
      raised[i] = depth >= note ? 1 : 0;
      flatRouted[i] = codeD8[i] === 0 || depth > 0.0 ? 1 : 0;
    }
    var maxFill = -Infinity;
    for (r = r0; r < r1; r++) {
      for (i = r * cols + c0; i < r * cols + c1; i++) {
        if (cls[i] === ROUTE_LAND && fillDepth[i] > maxFill) maxFill = fillDepth[i];
      }
    }
    if (maxFill === -Infinity) maxFill = 0.0;      // no land in the square shown
    fillDepth = keep(fillDepth);

    stage(0.6, phrase('terrain.stage_accumulate'));
    var totals = accumulateFlow(flats.code, cls, rows, cols, metric, !!grid.seaClean);
    var areaUnits = totals.areaUnits, flag = totals.flag;
    /** @type {TerrainCore} */
    var core = {
      rows: rows, cols: cols, shown: square, lons: lons, lats: lats, dx: metric.dx, dy: metric.dy, dg: metric.dg,
      count: totals.count, areaUnits: areaUnits, cls: cls, code: flats.code, flag: flag, raised: raised,
      flatRouted: flatRouted,
    };

    stage(0.7, phrase('terrain.stage_drainage'));
    var drawn = drainageLinks(core, settings.drainage_area_km2);
    var stream = new Uint8Array(n);
    for (i = 0; i < n; i++) stream[i] = cls[i] === ROUTE_LAND && areaUnits[i] >= threshold ? 1 : 0;

    stage(0.75, phrase('terrain.stage_shading'));
    var slope = hornGradients(zt, rows, cols, metric);
    var altitude = settings.hillshade_altitude_deg, zFactor = settings.hillshade_z_factor;
    var hillshades = settings.hillshade_panel_azimuths_deg.map(function (azimuth) {
      return keep(hillshadeLayer(slope.p, slope.q, azimuth, altitude, zFactor));
    });
    var hillshadeMulti = keep(multidirectionalHillshade(slope.p, slope.q, settings.hillshade_azimuths_deg,
      altitude, zFactor));

    var labelCurvature = phrase('terrain.stage_curvature');
    stage(0.85, labelCurvature);
    var wet = wetnessIndex(areaUnits, cls, slope.tanb, rows, cols, metric, settings.flat_tan_slope);
    var twi = keep(wet.twi), tanb = keep(slope.tanb);
    var bends = curvatures(zt, cls, rows, cols, metric, settings.curvature_spacing_m, settings.flat_tan_slope);
    /* one limit for both panels: |profile| of the square shown, then
     * |tangential|, as Python concatenates them */
    var bend = new Float64Array(2 * cells), at = 0, abs = Math.abs;
    for (var layer = 0; layer < 2; layer++) {
      var values = layer ? bends.tangential : bends.profile;
      for (r = r0; r < r1; r++) for (i = r * cols + c0; i < r * cols + c1; i++) bend[at++] = abs(values[i]);
    }
    var curvatureLimit = displayRange(bend, 0.98, 0.98)[0];
    var profile = keep(bends.profile), tangential = keep(bends.tangential);

    /* The relief counts every finite height of the square shown, sea with
     * a height included; the wetness range is chosen on the exact argument
     * and only the two chosen values pass through a logarithm. */
    var lowest = Infinity, highest = -Infinity, any = false;
    var arg = new Float64Array(cells);
    at = 0;
    var floored = 0, nRaised = 0;
    for (r = r0; r < r1; r++) {
      for (i = r * cols + c0; i < r * cols + c1; i++) {
        var height = zt[i];
        if (height - height === 0) {
          any = true;
          if (height < lowest) lowest = height;
          if (height > highest) highest = height;
        }
        arg[at++] = wet.arg[i];
        floored += wet.floored[i];
        nRaised += raised[i];
      }
    }
    var relief = any ? highest - lowest : NaN;
    var twiEnds = displayRange(arg, 0.02, 0.98);
    var lines = streamCounts(core, settings.drainage_area_km2);
    Object.assign(summary, {
      raised: nRaised, flat_routed_stream: lines.flat_routed_stream, stream: lines.stream,
      contaminated_stream: lines.contaminated_stream, unresolved: flats.unresolved, floored: floored,
      raised_pct: assemblyShare(nRaised, land), flat_routed_lines_pct: lines.flat_routed_lines_pct,
      contaminated_pct: lines.contaminated_pct, sea_pct: assemblyShare(sea + assumedShown, cells),
      zero_fill_pct: assemblyShare(zeroFill, cells), max_fill_m: maxFill, k_cells: bends.kCells,
      threshold_units: threshold, relief: relief, contour_interval: contourInterval(relief),
      twi_range: [Math.log(twiEnds[0]), Math.log(twiEnds[1])], curvature_limit: curvatureLimit,
    });
    stage(1.0, labelCurvature);
    return {
      grid: grid, metric: metric, core: core, filled: filled, fillDepth: fillDepth, unresolved: flats.unresolved,
      stream: stream, links: drawn.links, parts: drawn.parts, p: slope.p, q: slope.q, tanb: tanb,
      hillshades: hillshades, hillshadeMulti: hillshadeMulti, twiArg: wet.arg, twi: twi, profile: profile,
      tangential: tangential, kCells: bends.kCells, floored: floored, zeroFill: zeroFill, summary: summary,
      settings: settings,
    };
  }

  /**
   * The core an analysis traces its drainage lines from, as the worker
   * hands it to the page so that a new threshold re-traces the lines with
   * drainageLinks and nothing else: the core object of spec 5.1, its
   * Float64Array lons, lats, dx, dy, dg, count and areaUnits and its
   * Uint8Array cls, code, flag, raised and flatRouted. The arrays are the
   * analysis's own, not copies, so a worker that transfers them gives up
   * the analysis it took them from; each is a buffer of its own.
   * @param {TerrainAnalysis} analysis what analyseTerrain gives
   * @returns {TerrainCore}
   */
  function terrainCore(analysis) {
    var core = analysis.core;
    return {
      rows: core.rows, cols: core.cols, shown: core.shown.slice(), lons: core.lons, lats: core.lats,
      dx: core.dx, dy: core.dy, dg: core.dg, count: core.count, areaUnits: core.areaUnits, cls: core.cls,
      code: core.code, flag: core.flag, raised: core.raised, flatRouted: core.flatRouted,
    };
  }

  /* What the heights are heights of, by the product a grid was read as,
   * for a grid that came without a read report: terrain_analysis's
   * _surface_note. */
  function assemblySurfaceNote(sourceId) {
    if (sourceId === 'copernicus_glo30') return phrase('terrain.surface_copernicus');
    if (sourceId === 'srtm' || sourceId === 'hgt') return phrase('terrain.surface_srtm');
    return phrase('terrain.surface_unknown');
  }

  /* The radius and the margin of an analysed window, in km, measured
   * from the window itself for an analysis that came without a read's
   * plan: terrain_analysis._measured_window. With [r0, r1, c0, c1] =
   * core.shown and mid = floor((r0 + r1) / 2), the middle row shown, in
   * float64 and in this order (Python works out the same expressions, so
   * the two print the same figures):
   *   marginM = min(r0 * dy[r0], (rows - r1) * dy[r1 - 1], c0 * dx[mid], (cols - c1) * dx[mid])
   *   radiusM = min((r1 - r0) * dy[mid], (c1 - c0) * dx[mid]) / 2.0
   *   km = floor(m / 100.0) / 10.0
   * The margin is the narrowest of the four sides analysed beyond the
   * square shown, rows measured by the cell height of the shown row beside
   * them and columns by the cell width of the middle shown row; the radius
   * is half the shown square's shorter side. Both are floored to 0.1 km,
   * so that they never overstate what was analysed, and a margin under
   * 100 m is stated as none. */
  function measuredWindow(core) {
    var shown = core.shown, r0 = shown[0], r1 = shown[1], c0 = shown[2], c1 = shown[3];
    var mid = Math.floor((r0 + r1) / 2), width = core.dx[mid], height = core.dy[mid];
    var marginM = Math.min(r0 * core.dy[r0], (core.rows - r1) * core.dy[r1 - 1], c0 * width,
      (core.cols - c1) * width);
    var radiusM = Math.min((r1 - r0) * height, (c1 - c0) * width) / 2.0;
    return { radius: Math.floor(radiusM / 100.0) / 10.0, margin: Math.floor(marginM / 100.0) / 10.0 };
  }

  /* A caption giving `count` cells as a share of `cells` (the square
   * shown, or its land), by the read report's rule in whole numbers alone:
   * over none but under half a per cent, the `little` sentence with the
   * count instead of "0%"; else the `share` sentence, at most 99% while
   * any cell is not counted, never "100%", and 0% of none. `values` are
   * the sentences' other values. terrain_analysis._share_sentence. */
  function shareSentence(share, little, count, cells, values) {
    if (count > 0 && 200 * count < cells) return phrase(little, Object.assign({ count: count }, values));
    return phrase(share, Object.assign({ pct: cells ? elevationPercent(count, cells) : 0 }, values));
  }

  /**
   * Every sentence the terrain figures and the drainage lines carry, in
   * the catalogue's words, so that both apps print the same:
   * terrain_analysis.terrain_captions. `read` is the read the window came
   * from, or null: its surface note says what the heights are heights of
   * (else the grid's source decides), and its plan the radius and margin
   * of the window; without a plan both are measured from the analysed
   * window and the square shown (measuredWindow), so that a grid analysed
   * whole says it had no margin. `where` names the place, as the read
   * report does.
   *
   * The keys, in Python's order: title_relief, title_wetness,
   * title_curvature and title_directions; panel_0 onwards, the title of
   * each panel lit from one direction; relief, wetness, curvature and
   * directions, each figure's captions as one paragraph in the order they
   * are printed under it (the sea, a zero-filled gap, sea in a file of
   * unstated source and an unresolved flat are mentioned only where the
   * square shows one, but sea of unstated source for the wetness index
   * and the description wherever the analysed window holds some);
   * figure_caveat, the line drawn inside every figure;
   * geojson_description; and the analysis's stage labels, stage_classes to
   * stage_curvature.
   * @param {TerrainAnalysis} analysis what analyseTerrain gives
   * @param {Rec|null|undefined} read what readElevationWindow gives, or null for a grid read some other
   *   way
   * @param {string} where the place, as the read report names it
   * @returns {Record<string, string>}
   */
  function terrainCaptions(analysis, read, where) {
    var cfg = analysis.settings, summary = analysis.summary, grid = analysis.grid;
    var surface = read && read.surface ? read.surface : assemblySurfaceNote(grid.sourceId);
    var measured = read && read.plan ? { radius: read.plan.radiusKm, margin: read.plan.marginKm }
      : measuredWindow(analysis.core);
    var radius = measured.radius, margin = measured.margin;
    var level = cfg.sea_level_m;
    var candidates = phrase('terrain.caption_candidates');
    var cells = summary.cells, sea = summary.sea + summary.assumed_sea;
    /* the lines and the lightened cells may drain sea anywhere in the
     * analysed window, the margin included, not only in the square shown */
    var unstated = !grid.seaClean, cls = analysis.core.cls, windowSea = false;
    for (var i = 0; i < cls.length && !windowSea; i++) windowSea = cls[i] === ROUTE_SEA;
    var seaUnstated = unstated && windowSea;

    var relief = [
      phrase('terrain.caption_relief', { interval: summary.contour_interval, area: cfg.drainage_area_km2 }),
      shareSentence('terrain.caption_fill', 'terrain.caption_fill_little', summary.raised, summary.land,
        { lines_pct: summary.flat_routed_lines_pct, depth: cfg.fill_note_m }),
      margin > 0 ? phrase('terrain.caption_edge', { margin: margin }) : phrase('terrain.caption_edge_none'),
    ];
    if (sea > 0) {
      relief.push(shareSentence('terrain.caption_sea', 'terrain.caption_sea_little', sea, cells, { level: level }));
    }
    if (unstated && sea > 0) relief.push(phrase('terrain.caption_sea_unstated', { level: level }));
    if (summary.zero_fill > 0) {
      relief.push(shareSentence('terrain.caption_zero_fill', 'terrain.caption_zero_fill_little', summary.zero_fill,
        cells, { level: level }));
    }
    if (summary.unresolved > 0) relief.push(phrase('terrain.caption_unresolved', { n: summary.unresolved }));
    relief.push(candidates);
    /* the spacing the curvature was taken over, in metres of the middle row */
    var mid = Math.floor(analysis.core.rows / 2);
    var spacing = analysis.kCells * ((analysis.core.dx[mid] + analysis.core.dy[mid]) / 2.0);
    var azimuths = cfg.hillshade_panel_azimuths_deg.slice();
    if (!azimuths.length) {
      /* Python's and_join raises on an empty list, so both refuse */
      throw new Error('the hillshade panels need at least one azimuth');
    }

    /** @type {Record<string, string>} */
    var out = {
      title_relief: phrase('terrain.title_relief', { where: where }),
      title_wetness: phrase('terrain.title_wetness', { where: where }),
      title_curvature: phrase('terrain.title_curvature', { where: where }),
      title_directions: phrase('terrain.title_directions', { where: where }),
    };
    azimuths.forEach(function (azimuth, t) { out['panel_' + t] = phrase('terrain.panel_azimuth', { az: azimuth }); });
    out.relief = relief.join(' ');
    var wetness = [phrase('terrain.caption_twi', { floor: cfg.flat_tan_slope, n: summary.floored })];
    if (seaUnstated) wetness.push(phrase('terrain.caption_sea_unstated', { level: level }));
    out.wetness = wetness.concat([candidates, surface]).join(' ');
    out.curvature = [phrase('terrain.caption_curvature', { spacing: spacing, floor: cfg.flat_tan_slope }),
      candidates, surface].join(' ');
    out.directions = phrase('terrain.caption_directions', {
      azimuths: andJoin(azimuths.map(function (azimuth) { return formatG(Number(azimuth)) + '°'; })),
      altitude: cfg.hillshade_altitude_deg });
    out.figure_caveat = phrase('terrain.figure_caveat', { surface: surface });
    out.geojson_description = geojsonDescription(grid.label, cfg.drainage_area_km2, radius, where, margin,
      cfg.fill_note_m, surface, seaUnstated, level);
    out.stage_classes = phrase('terrain.stage_classes');
    out.stage_fill = phrase('terrain.stage_fill');
    out.stage_flow = phrase('terrain.stage_flow');
    out.stage_flats = phrase('terrain.stage_flats');
    out.stage_accumulate = phrase('terrain.stage_accumulate');
    out.stage_drainage = phrase('terrain.stage_drainage');
    out.stage_shading = phrase('terrain.stage_shading');
    out.stage_curvature = phrase('terrain.stage_curvature');
    return out;
  }

  /**
   * The layers the four terrain figures draw, as the worker hands them to
   * the page: cropped to the square shown and decimated by one whole
   * stride, ceil(max(Ws, Hs) / maxEdge), so that neither side has more
   * than maxEdge cells; each kept cell is the one at the stride's start,
   * a[r0 + y*stride][c0 + x*stride], never an average, so a class or a
   * mask is never blended and a value is one the analysis gave. Python has
   * no twin: its figures draw the full layers, and nothing here is
   * compared between engines, only held by its own test to the cells it
   * keeps.
   *
   * The continuous layers are Float32Array (the heights, the composite
   * and panel hillshades, the wetness index and both curvatures); the
   * classes and masks are Uint8Array (cls, assumedSea, raised, stream and
   * the uncertain-area flag); lons and lats are the kept cells' centres.
   * Every array is new, so the worker can transfer them all.
   * @param {TerrainAnalysis} analysis what analyseTerrain gives
   * @param {TerrainGrid|null} grid the grid it analysed, for its heights and assumed sea (the analysis's
   *   own when null)
   * @param {number} maxEdge the most cells a side may keep, a whole number from 1
   * @returns {Rec} {rows, cols, stride, shown, lons, lats, z, hillshadeMulti, hillshades, twi, profile,
   *   tangential, cls, assumedSea, raised, stream, flag}
   */
  function terrainDisplayLayers(analysis, grid, maxEdge) {
    if (!(Number.isInteger(maxEdge) && maxEdge >= 1)) {
      throw new Error('a display layer needs a whole number of cells a side from 1, not ' + maxEdge);
    }
    var from = grid || analysis.grid, core = analysis.core, cols = core.cols, shown = core.shown;
    if (from.z.length !== core.rows * cols) {
      throw new Error('the grid holds ' + from.z.length + ' heights, not the ' + core.rows * cols + ' analysed');
    }
    var r0 = shown[0], c0 = shown[2], high = shown[1] - r0, wide = shown[3] - c0;
    var stride = Math.ceil(Math.max(wide, high) / maxEdge);
    var outRows = Math.ceil(high / stride), outCols = Math.ceil(wide / stride);
    var pick = function (layer, Kind) {
      var out = new Kind(outRows * outCols);
      for (var y = 0; y < outRows; y++) {
        var at = (r0 + y * stride) * cols + c0;
        for (var x = 0; x < outCols; x++) out[y * outCols + x] = layer[at + x * stride];
      }
      return out;
    };
    var lons = new Float64Array(outCols), lats = new Float64Array(outRows), k;
    for (k = 0; k < outCols; k++) lons[k] = core.lons[c0 + k * stride];
    for (k = 0; k < outRows; k++) lats[k] = core.lats[r0 + k * stride];
    var sea = from.assumedSea || new Uint8Array(core.rows * cols);
    return {
      rows: outRows, cols: outCols, stride: stride, shown: shown.slice(), lons: lons, lats: lats,
      z: pick(from.z, Float32Array), hillshadeMulti: pick(analysis.hillshadeMulti, Float32Array),
      hillshades: analysis.hillshades.map(function (layer) { return pick(layer, Float32Array); }),
      twi: pick(analysis.twi, Float32Array), profile: pick(analysis.profile, Float32Array),
      tangential: pick(analysis.tangential, Float32Array), cls: pick(core.cls, Uint8Array),
      assumedSea: pick(sea, Uint8Array), raised: pick(core.raised, Uint8Array),
      stream: pick(analysis.stream, Uint8Array), flag: pick(core.flag, Uint8Array),
    };
  }

  Object.assign(C, {
    analyseTerrain: analyseTerrain, terrainCore: terrainCore, drainageLinks: drainageLinks, streamCounts: streamCounts,
    drainageGeoJson: drainageGeoJson, terrainCaptions: terrainCaptions, terrainDisplayLayers: terrainDisplayLayers,
  });

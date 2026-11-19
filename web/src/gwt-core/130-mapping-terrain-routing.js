
  /* ============================================== Terrain analysis: routing
   * groundwater/mapping/terrain_analysis.py's routing core: where water
   * goes on an elevation model, and how much ground drains through each
   * cell. classifyCells says which cells are land, sea or no data, and
   * voids a sea area whose edge runs straight along the grid, the mark of
   * a 0 m fill rather than a coast. fillDepressions raises every hollow to
   * the height it spills at. flowDirections gives each land cell its
   * steepest (D8) neighbour on that surface, and resolveFlats routes the
   * cells left level across their flat, away from higher ground and
   * towards lower (Barnes, Lehman and Mulla 2014). accumulateFlow counts
   * the cells and adds up the ground upstream of each, flagging what
   * drains in from the window's edge, from beside a void or, for a source
   * not known to write sea as 0 m, from beside the sea.
   *
   * Grids are south row first and row-major, as readElevationWindow gives
   * them: cell i = r * cols + c, and north is row + 1. Every scan visits
   * the eight neighbours in one order, E, S, W, N, SE, SW, NW, NE, which
   * settles every tie; Python's vectorised twin settles each the same way,
   * so the engines agree to the bit on the classes, the filled surface
   * (one answer however it is found, once -0 is gone), the codes and the
   * counts. Counts and areas are whole numbers held in Float64Array, exact
   * below 2^53 in any order: an Int32Array or Uint32Array would wrap past
   * 2^32 units of 0.01 square metres (one catchment in the default window
   * reaches about 4e10) and a Float32Array would round a count across the
   * stream threshold. Everything is synchronous and DOM-free, for the
   * worker and the Node sandboxes alike. */

  /* The neighbour order K as (row, column) steps, north being row + 1, and
   * the ESRI code each direction is written with. */
  var ROUTE_DR = [0, -1, 0, 1, -1, -1, 1, 1];
  var ROUTE_DC = [1, 0, -1, 0, 1, -1, -1, 1];
  var ROUTE_ESRI = [1, 4, 16, 64, 2, 8, 32, 128];
  /* the k an ESRI code names: -1 for 0 (no direction), 255 (leaves the
   * analysis) and anything else */
  var ROUTE_K_OF_CODE = (function () {
    var out = new Int8Array(256).fill(-1);
    for (var k = 0; k < 8; k++) out[ROUTE_ESRI[k]] = k;
    return out;
  }());
  var ROUTE_VOID = 0, ROUTE_LAND = 1, ROUTE_SEA = 2;

  /* the number of cells in a rows by cols grid, after checking that each
   * array given for it holds one value a cell (a grid with no cells routes
   * to empty layers, in both engines) */
  function routeCells(rows, cols, arrays) {
    if (!(Number.isInteger(rows) && Number.isInteger(cols) && rows >= 0 && cols >= 0)) {
      throw new Error('a grid of ' + rows + ' by ' + cols + ' cells has no shape to route');
    }
    var n = rows * cols;
    for (var a = 0; a < arrays.length; a++) {
      if (arrays[a].length !== n) {
        throw new Error('a ' + rows + ' by ' + cols + ' grid holds ' + n + ' cells, not ' + arrays[a].length);
      }
    }
    return n;
  }

  /* A metric gives each row its own value, once (rowMetric's arrays for
   * this grid). Both engines refuse one of any other length, which would be
   * read past its end as NaN or belong to another grid. */
  function routeRows(what, values, rows) {
    if (values.length !== rows) {
      throw new Error('the metric gives ' + values.length + ' ' + what + ', not one for each of ' + rows + ' rows');
    }
  }

  /* Spread a code through the 8-connected cells holding another, from the
   * first `tail` cells of `queue`, which already hold it: every cell
   * reached changes from `from` to `to` and joins the queue's end. */
  function routeSpread(cls, from, to, queue, tail, rows, cols) {
    for (var head = 0; head < tail; head++) {
      var i = queue[head], r = (i / cols) | 0, c = i - r * cols;
      for (var k = 0; k < 8; k++) {
        var rr = r + ROUTE_DR[k], cc = c + ROUTE_DC[k];
        if (rr < 0 || rr >= rows || cc < 0 || cc >= cols) continue;
        var j = rr * cols + cc;
        if (cls[j] === from) {
          cls[j] = to;
          queue[tail++] = j;
        }
      }
    }
  }

  /**
   * Which cells are land, sea or no data: terrain_analysis.classify_cells.
   * Sea is ground at or below `seaLevel` joined, cell to diagonal cell, to
   * the grid's edge or to a missing tile taken as sea;
   * low ground inland that is not joined stays land, to be filled. A sea
   * area that meets land along a straight row or column of `straightEdge`
   * cells or more is not a coast but a mosaic's 0 m fill - real coasts
   * zigzag across the lattice, in runs of at most 45 cells on Sierra
   * Leone's tiles - so the whole of it becomes no data (`zeroFill`) and
   * drainage ends at it flagged, rather than 100 km inland, unflagged.
   * Every height goes through `+ 0` first, so a -0 reads as 0 and the two
   * engines' fills cannot differ in a zero's sign.
   * @param {ArrayLike<number>} z heights in metres, south row first; NaN or an infinity where there is none
   * @param {number} rows the grid's rows
   * @param {number} cols the grid's columns
   * @param {number} seaLevel the height at or below which ground joined to the edge is sea (terrain.sea_level_m)
   * @param {ArrayLike<number>|null} [assumedSea] 1 where a missing tile was taken as sea, with no height;
   *   null or left out for none
   * @param {number|null} [straightEdge] the straight run of sea edge, in cells, that marks a 0 m fill
   *   (terrain.sea_straight_edge_cells; 150 when left out)
   * @returns {{cls: Uint8Array, seed: Uint8Array, zeroFill: Uint8Array, zt: Float64Array}} cls 0 no data
   *   (the zero-filled cells included), 1 land, 2 sea; seed 1 on the land cells on the edge or beside sea
   *   or no data; zeroFill 1 on the cells moved from sea to no data; zt the working heights, NaN on no
   *   data and on assumed sea
   */
  function classifyCells(z, rows, cols, seaLevel, assumedSea, straightEdge) {
    var n = routeCells(rows, cols, assumedSea ? [z, assumedSea] : [z]);
    var longest = straightEdge === undefined || straightEdge === null ? 150 : straightEdge;   // as None in Python
    var cls = new Uint8Array(n), seed = new Uint8Array(n), zeroFill = new Uint8Array(n);
    var zt = new Float64Array(n), queue = new Int32Array(n);
    /* working codes besides the three classes: a sea candidate not (yet)
     * joined to the edge, and a cell of a zero-filled area */
    var CANDIDATE = 3, ZERO = 4;
    var i, r, c, k, j, a, b, run, tail, v;
    for (i = 0; i < n; i++) {
      v = z[i];
      if (assumedSea && assumedSea[i]) {
        cls[i] = CANDIDATE;
        zt[i] = NaN;
      } else if (typeof v === 'number' && v - v === 0) {   // finite: NaN and the infinities give NaN
        zt[i] = v + 0.0;
        cls[i] = zt[i] <= seaLevel ? CANDIDATE : ROUTE_LAND;
      } else {
        zt[i] = NaN;
      }
    }

    /* sea: the candidates joined to one on the edge or to assumed sea,
     * spread from those cells in ascending order */
    tail = 0;
    for (i = 0; i < n; i++) {
      if (cls[i] !== CANDIDATE) continue;
      r = (i / cols) | 0;
      c = i - r * cols;
      if (r === 0 || r === rows - 1 || c === 0 || c === cols - 1 || (assumedSea && assumedSea[i])) {
        cls[i] = ROUTE_SEA;
        queue[tail++] = i;
      }
    }
    routeSpread(cls, CANDIDATE, ROUTE_SEA, queue, tail, rows, cols);
    for (i = 0; i < n; i++) if (cls[i] === CANDIDATE) cls[i] = ROUTE_LAND;

    /* The straight edges: runs of row pairs (r, r + 1) along the columns,
     * then of column pairs (c, c + 1) along the rows, where one cell is
     * sea with a height and the other land. The sea cell of each pair in a
     * run of `longest` or more is marked in zeroFill for now. */
    for (r = 0; r + 1 < rows; r++) {
      run = 0;
      for (c = 0; c <= cols; c++) {
        a = r * cols + c;
        b = a + cols;
        if (c < cols && ((cls[a] === ROUTE_SEA && zt[a] === zt[a] && cls[b] === ROUTE_LAND) ||
                         (cls[a] === ROUTE_LAND && cls[b] === ROUTE_SEA && zt[b] === zt[b]))) {
          run += 1;
          continue;
        }
        if (run >= longest) {
          for (a = r * cols + c - run; a < r * cols + c; a++) zeroFill[cls[a] === ROUTE_SEA ? a : a + cols] = 1;
        }
        run = 0;
      }
    }
    for (c = 0; c + 1 < cols; c++) {
      run = 0;
      for (r = 0; r <= rows; r++) {
        a = r * cols + c;
        b = a + 1;
        if (r < rows && ((cls[a] === ROUTE_SEA && zt[a] === zt[a] && cls[b] === ROUTE_LAND) ||
                         (cls[a] === ROUTE_LAND && cls[b] === ROUTE_SEA && zt[b] === zt[b]))) {
          run += 1;
          continue;
        }
        if (run >= longest) {
          for (var s = r - run; s < r; s++) {
            a = s * cols + c;
            zeroFill[cls[a] === ROUTE_SEA ? a : a + 1] = 1;
          }
        }
        run = 0;
      }
    }
    /* each marked cell's whole sea area, assumed sea in it included,
     * becomes no data */
    tail = 0;
    for (i = 0; i < n; i++) {
      if (zeroFill[i]) {
        cls[i] = ZERO;
        queue[tail++] = i;
      }
    }
    if (tail) {
      routeSpread(cls, ROUTE_SEA, ZERO, queue, tail, rows, cols);
      for (i = 0; i < n; i++) {
        if (cls[i] !== ZERO) continue;
        cls[i] = ROUTE_VOID;
        zeroFill[i] = 1;
        zt[i] = NaN;
      }
    }

    /* the seeds: land on the edge, or beside sea or no data (found from
     * the sea and no data, which are few, rather than from every cell) */
    for (r = 0; r < rows; r++) {
      for (c = 0; c < cols; c++) {
        i = r * cols + c;
        if (cls[i] === ROUTE_LAND) {
          if (r === 0 || r === rows - 1 || c === 0 || c === cols - 1) seed[i] = 1;
          continue;
        }
        for (k = 0; k < 8; k++) {
          var rr = r + ROUTE_DR[k], cc = c + ROUTE_DC[k];
          if (rr < 0 || rr >= rows || cc < 0 || cc >= cols) continue;
          j = rr * cols + cc;
          if (cls[j] === ROUTE_LAND) seed[j] = 1;
        }
      }
    }
    return { cls: cls, seed: seed, zeroFill: zeroFill, zt: zt };
  }

  /**
   * The depression-filled surface: terrain_analysis.fill_depressions.
   * Each land cell is raised to the lowest height at which
   * water standing on it could reach a seed - the least, over the land
   * paths to a seed, of the highest cell on the path - so every land cell
   * has a way out that never climbs. The fill is unique, so this
   * Priority-Flood (Barnes, Lehman and Mulla 2014, with the queue of cells
   * already settled at their pit's spill height) gives the bits Python's
   * basin graph gives. Seeds keep their height, sea keeps its own (NaN on
   * assumed sea) and no data stays NaN; land with no path to a seed, which
   * only a seed mask other than classifyCells' can leave, is +Infinity.
   * @param {ArrayLike<number>} zt the working heights classifyCells gives
   * @param {ArrayLike<number>} cls the classes classifyCells gives: 0 no data, 1 land, 2 sea
   * @param {ArrayLike<number>} seed 1 on the land cells water may leave the grid from
   * @param {number} rows the grid's rows
   * @param {number} cols the grid's columns
   * @returns {Float64Array} the filled heights, south row first
   */
  function fillDepressions(zt, cls, seed, rows, cols) {
    var n = routeCells(rows, cols, [zt, cls, seed]);
    var filled = new Float64Array(n), closed = new Uint8Array(n);
    var i;
    for (i = 0; i < n; i++) {
      if (cls[i] === ROUTE_LAND) {
        filled[i] = zt[i];
      } else {
        filled[i] = cls[i] === ROUTE_SEA ? zt[i] : NaN;
        closed[i] = 1;
      }
    }
    /* A binary min-heap keyed by (height, the order cells were put in),
     * grown as needed; and the pit queue, first in first out, which holds
     * each cell at most once. */
    var size = 0, order = 0, capacity = 1024;
    var keys = new Float64Array(capacity), seqs = new Float64Array(capacity), cells = new Int32Array(capacity);
    var pit = new Int32Array(n), pitHead = 0, pitTail = 0;
    var push = function (key, cell) {
      if (size === capacity) {
        capacity *= 2;
        var k2 = new Float64Array(capacity), s2 = new Float64Array(capacity), c2 = new Int32Array(capacity);
        k2.set(keys);
        s2.set(seqs);
        c2.set(cells);
        keys = k2;
        seqs = s2;
        cells = c2;
      }
      var seq = order++, at = size++;
      while (at > 0) {
        var up = (at - 1) >> 1;
        if (keys[up] < key || (keys[up] === key && seqs[up] < seq)) break;
        keys[at] = keys[up];
        seqs[at] = seqs[up];
        cells[at] = cells[up];
        at = up;
      }
      keys[at] = key;
      seqs[at] = seq;
      cells[at] = cell;
    };
    var pop = function () {
      var top = cells[0];
      size -= 1;
      if (size > 0) {
        var key = keys[size], seq = seqs[size], cell = cells[size], at = 0;
        for (;;) {
          var least = 2 * at + 1;
          if (least >= size) break;
          var right = least + 1;
          if (right < size && (keys[right] < keys[least] ||
                               (keys[right] === keys[least] && seqs[right] < seqs[least]))) least = right;
          if (!(keys[least] < key || (keys[least] === key && seqs[least] < seq))) break;
          keys[at] = keys[least];
          seqs[at] = seqs[least];
          cells[at] = cells[least];
          at = least;
        }
        keys[at] = key;
        seqs[at] = seq;
        cells[at] = cell;
      }
      return top;
    };
    for (i = 0; i < n; i++) {
      if (cls[i] === ROUTE_LAND && seed[i]) {
        closed[i] = 1;
        push(filled[i], i);
      }
    }
    while (pitHead < pitTail || size > 0) {
      var cell = pitHead < pitTail ? pit[pitHead++] : pop();
      var level = filled[cell], r = (cell / cols) | 0, c = cell - r * cols;
      for (var k = 0; k < 8; k++) {
        var rr = r + ROUTE_DR[k], cc = c + ROUTE_DC[k];
        if (rr < 0 || rr >= rows || cc < 0 || cc >= cols) continue;
        var j = rr * cols + cc;
        if (closed[j]) continue;
        closed[j] = 1;
        if (filled[j] <= level) {
          filled[j] = level;
          pit[pitTail++] = j;
        } else {
          push(filled[j], j);
        }
      }
    }
    /* land the flood never reached has no path to a seed: the least over
     * no paths is +Infinity, which Python's basin graph gives too. Only a
     * seed mask other than classifyCells' leaves such land. */
    for (i = 0; i < n; i++) if (cls[i] === ROUTE_LAND && !closed[i]) filled[i] = Infinity;
    return filled;
  }

  /**
   * Each land cell's steepest way down on the filled surface, as an ESRI
   * D8 code: terrain_analysis.flow_directions. The drop to each
   * neighbour is divided by the distance between the cell centres in the
   * cell's own row; land and sea neighbours take part (sea at its own
   * height, assumed sea at sea level) and no data does not. Only a
   * neighbour whose height is below the cell's is ranked, by its drop, so
   * a drop that underflows to 0 still counts as a way down. The first
   * steepest neighbour in the order E, S, W, N, SE, SW, NW, NE wins a tie,
   * so ties go to cardinals first. A seed with no neighbour below it
   * flows out of the analysis (255); any other land cell with none is
   * level (0), for resolveFlats; every cell that is not land is 0.
   * @param {ArrayLike<number>} zt the working heights classifyCells gives
   * @param {ArrayLike<number>} filled the heights fillDepressions gives
   * @param {ArrayLike<number>} cls the classes: 0 no data, 1 land, 2 sea
   * @param {ArrayLike<number>} seed 1 on the land cells water may leave the grid from
   * @param {number} rows the grid's rows
   * @param {number} cols the grid's columns
   * @param {{dx: ArrayLike<number>, dy: ArrayLike<number>, dg: ArrayLike<number>}} metric each row's cell
   *   width, height and diagonal in metres, as rowMetric gives them
   * @param {number} seaLevel the height assumed sea stands at (terrain.sea_level_m)
   * @returns {Uint8Array} the D8 codes, south row first
   */
  function flowDirections(zt, filled, cls, seed, rows, cols, metric, seaLevel) {
    var n = routeCells(rows, cols, [zt, filled, cls, seed]);
    routeRows('cell widths', metric.dx, rows);
    routeRows('cell heights', metric.dy, rows);
    routeRows('cell diagonals', metric.dg, rows);
    var code = new Uint8Array(n), dist = new Float64Array(8);
    for (var r = 0; r < rows; r++) {
      dist[0] = dist[2] = metric.dx[r];
      dist[1] = dist[3] = metric.dy[r];
      dist[4] = dist[5] = dist[6] = dist[7] = metric.dg[r];
      for (var c = 0; c < cols; c++) {
        var i = r * cols + c;
        if (cls[i] !== ROUTE_LAND) continue;
        var here = filled[i], best = 0.0, bk = -1;
        for (var k = 0; k < 8; k++) {
          var rr = r + ROUTE_DR[k], cc = c + ROUTE_DC[k];
          if (rr < 0 || rr >= rows || cc < 0 || cc >= cols) continue;
          var j = rr * cols + cc, kind = cls[j];
          if (kind === ROUTE_VOID) continue;
          var there = kind === ROUTE_LAND ? filled[j] : (Number.isFinite(zt[j]) ? zt[j] : seaLevel);
          var drop = (here - there) / dist[k];
          /* lower is decided on the heights, not on the drop's sign: a
           * difference of a few times 2^-1074 divided by some thirty metres
           * rounds to +0, and the cell would be taken for a pit */
          if (here > there && (bk < 0 || drop > best)) {
            best = drop;
            bk = k;
          }
        }
        code[i] = bk >= 0 ? ROUTE_ESRI[bk] : (seed[i] ? 255 : 0);
      }
    }
    return code;
  }

  /* Breadth-first levels over a flat: the cells already at level 1 are the
   * first `tail` of `queue`; each step moves to a level (code 0) land
   * neighbour of the same filled height not yet reached. */
  function routeFlatLevels(level, queue, tail, filled, cls, codeD8, rows, cols) {
    for (var head = 0; head < tail; head++) {
      var i = queue[head], r = (i / cols) | 0, c = i - r * cols, here = filled[i], next = level[i] + 1;
      for (var k = 0; k < 8; k++) {
        var rr = r + ROUTE_DR[k], cc = c + ROUTE_DC[k];
        if (rr < 0 || rr >= rows || cc < 0 || cc >= cols) continue;
        var j = rr * cols + cc;
        if (level[j] === 0 && cls[j] === ROUTE_LAND && codeD8[j] === 0 && filled[j] === here) {
          level[j] = next;
          queue[tail++] = j;
        }
      }
    }
  }

  /**
   * Directions across flats: terrain_analysis.resolve_flats, after
   * Barnes, Lehman and Mulla (2014). A level land cell (D8 code 0) is
   * routed down a mask that falls away from the higher ground beside its
   * flat and towards the flat's lower edge, the second weighted double so
   * that the way out always wins. One maximum over the whole grid stands
   * in for Barnes's per-flat maximum: within a flat the two differ by a
   * constant, so every comparison, and so every direction, is the same,
   * and the flats need no labels. Ties go to the first neighbour in the
   * order E, S, W, N, SE, SW, NW, NE. On a filled surface every level cell
   * has a way out; `unresolved` counts any that find none, which keep 0.
   * @param {ArrayLike<number>} filled the heights fillDepressions gives
   * @param {ArrayLike<number>} cls the classes: 0 no data, 1 land, 2 sea
   * @param {ArrayLike<number>} codeD8 the codes flowDirections gives
   * @param {number} rows the grid's rows
   * @param {number} cols the grid's columns
   * @returns {{code: Uint8Array, unresolved: number}} the codes with the level cells routed
   */
  function resolveFlats(filled, cls, codeD8, rows, cols) {
    var n = routeCells(rows, cols, [filled, cls, codeD8]);
    var code = new Uint8Array(n);
    code.set(codeD8);
    var away = new Int32Array(n), towards = new Int32Array(n), queue = new Int32Array(n);
    var i, r, c, k, rr, cc, j, here, tail;
    /* The high edges (level cells beside higher land) start the away
     * levels, the low edges (cells with a way down beside a level cell of
     * their height) the towards levels. Both are found from the level
     * cells, a few in each hundred, rather than from every cell. */
    for (r = 0; r < rows; r++) {
      for (c = 0; c < cols; c++) {
        i = r * cols + c;
        if (cls[i] !== ROUTE_LAND || codeD8[i] !== 0) continue;
        here = filled[i];
        for (k = 0; k < 8; k++) {
          rr = r + ROUTE_DR[k];
          cc = c + ROUTE_DC[k];
          if (rr < 0 || rr >= rows || cc < 0 || cc >= cols) continue;
          j = rr * cols + cc;
          if (cls[j] !== ROUTE_LAND) continue;
          if (filled[j] > here) away[i] = 1;
          else if (codeD8[j] !== 0 && filled[j] === here) towards[j] = 1;
        }
      }
    }
    tail = 0;
    for (i = 0; i < n; i++) if (away[i]) queue[tail++] = i;
    routeFlatLevels(away, queue, tail, filled, cls, codeD8, rows, cols);
    tail = 0;
    for (i = 0; i < n; i++) if (towards[i]) queue[tail++] = i;
    routeFlatLevels(towards, queue, tail, filled, cls, codeD8, rows, cols);
    var most = 0;
    for (i = 0; i < n; i++) if (away[i] > most) most = away[i];
    /* the mask, written over the away levels: (most - away) + 2 towards
     * where the away pass reached, 2 towards elsewhere (0 off the flats) */
    for (i = 0; i < n; i++) away[i] = away[i] > 0 ? (most - away[i]) + 2 * towards[i] : 2 * towards[i];
    var mask = away, unresolved = 0;
    for (r = 0; r < rows; r++) {
      for (c = 0; c < cols; c++) {
        i = r * cols + c;
        if (cls[i] !== ROUTE_LAND || codeD8[i] !== 0) continue;
        here = filled[i];
        var best = mask[i], bk = -1;
        for (k = 0; k < 8; k++) {
          rr = r + ROUTE_DR[k];
          cc = c + ROUTE_DC[k];
          if (rr < 0 || rr >= rows || cc < 0 || cc >= cols) continue;
          j = rr * cols + cc;
          if (cls[j] === ROUTE_LAND && filled[j] === here && mask[j] < best) {
            best = mask[j];
            bk = k;
          }
        }
        if (bk >= 0) code[i] = ROUTE_ESRI[bk];
        else unresolved += 1;
      }
    }
    return { code: code, unresolved: unresolved };
  }

  /**
   * How much drains through each land cell: terrain_analysis.accumulate_flow.
   * `count` is the cells upstream, the cell itself included
   * (TauDEM and Whitebox count it; ESRI's is one less), and `areaUnits`
   * their ground in whole units of 0.01 square metres, each cell its row's
   * auRow, so both are exact whatever order cells are added in. `flag`
   * marks a cell some of whose upstream ground lies on the window's edge,
   * beside no data or, unless `seaClean`, beside sea: ground beyond those
   * may drain in or out unseen, so the area there is uncertain either way
   * (TauDEM's AreaD8 rule, flagging instead of deleting). Cells that are
   * not land hold 0 in all three.
   * @param {ArrayLike<number>} code the codes resolveFlats gives
   * @param {ArrayLike<number>} cls the classes: 0 no data, 1 land, 2 sea
   * @param {number} rows the grid's rows
   * @param {number} cols the grid's columns
   * @param {{auRow: ArrayLike<number>}} metric each row's cell area in whole units of 0.01 square metres,
   *   as rowMetric gives it
   * @param {boolean} seaClean whether the source is known to write sea as 0 m, so sea flags nothing
   * @returns {{count: Float64Array, areaUnits: Float64Array, flag: Uint8Array}}
   */
  function accumulateFlow(code, cls, rows, cols, metric, seaClean) {
    var n = routeCells(rows, cols, [code, cls]);
    routeRows('cell areas', metric.auRow, rows);
    /* Both engines refuse a cell area that is not a whole number of units,
     * or so large that the largest times the cells reaches 2^53: Python's
     * int64 would cut off a fraction that a Float64Array keeps, and past
     * 2^53 the totals here would round where Python's are exact. A -0 is
     * taken as 0, as int64 takes it. */
    var auRow = new Float64Array(rows), most = 0;
    for (var a = 0; a < rows; a++) {
      auRow[a] = metric.auRow[a] + 0;
      if (!(Number.isInteger(auRow[a]) && auRow[a] >= 0)) {
        throw new Error('a cell area of ' + auRow[a] + ' is not a whole number of 0.01 m^2 units');
      }
      if (auRow[a] > most) most = auRow[a];
    }
    if (!(most * n < 9007199254740992)) {
      throw new Error('cell areas of up to ' + most + ' units over ' + n + ' cells could total 2^53 or more');
    }
    var down = new Int32Array(n).fill(-1), inflow = new Uint8Array(n), queue = new Int32Array(n);
    var count = new Float64Array(n), areaUnits = new Float64Array(n), flag = new Uint8Array(n);
    var i, r, c, k, rr, cc, j;
    for (r = 0; r < rows; r++) {
      for (c = 0; c < cols; c++) {
        i = r * cols + c;
        if (cls[i] !== ROUTE_LAND) {
          /* the land beside no data, or beside sea from a source that may
           * write a 0 m fill as sea, is flagged from the other side */
          if (cls[i] === ROUTE_SEA && seaClean) continue;
          for (k = 0; k < 8; k++) {
            rr = r + ROUTE_DR[k];
            cc = c + ROUTE_DC[k];
            if (rr < 0 || rr >= rows || cc < 0 || cc >= cols) continue;
            j = rr * cols + cc;
            if (cls[j] === ROUTE_LAND) flag[j] = 1;
          }
          continue;
        }
        count[i] = 1;
        areaUnits[i] = auRow[r];
        if (r === 0 || r === rows - 1 || c === 0 || c === cols - 1) flag[i] = 1;
        k = ROUTE_K_OF_CODE[code[i]];
        if (!(k >= 0)) continue;
        rr = r + ROUTE_DR[k];
        cc = c + ROUTE_DC[k];
        if (rr < 0 || rr >= rows || cc < 0 || cc >= cols) continue;
        j = rr * cols + cc;
        if (cls[j] !== ROUTE_LAND) continue;
        down[i] = j;
        inflow[j] += 1;
      }
    }
    /* Kahn's order: a cell passes its totals on once everything upstream
     * of it has */
    var tail = 0;
    for (i = 0; i < n; i++) if (cls[i] === ROUTE_LAND && inflow[i] === 0) queue[tail++] = i;
    for (var head = 0; head < tail; head++) {
      i = queue[head];
      j = down[i];
      if (j < 0) continue;
      count[j] += count[i];
      areaUnits[j] += areaUnits[i];
      flag[j] |= flag[i];
      inflow[j] -= 1;
      if (inflow[j] === 0) queue[tail++] = j;
    }
    /* a cell still waiting for inflow lies on a loop of directions, which
     * Kahn's order never reaches: its totals, and those of all that drains
     * into the loop, would come back short without a word */
    for (i = 0; i < n; i++) if (inflow[i] > 0) throw new Error('the flow directions form a loop');
    return { count: count, areaUnits: areaUnits, flag: flag };
  }

  Object.assign(C, {
    classifyCells: classifyCells, fillDepressions: fillDepressions, flowDirections: flowDirections,
    resolveFlats: resolveFlats, accumulateFlow: accumulateFlow,
  });

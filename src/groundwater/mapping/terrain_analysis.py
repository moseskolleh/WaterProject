"""Terrain analysis: where water falling on the ground would run, worked
out from the heights alone.

This module turns a window of an elevation model, as :mod:`.elevation`
reads it, into the layers the terrain figures and the drainage lines are
drawn from. Nothing here draws, and nothing imported here loads pyplot, so
the browser's Pyodide build and a caller after the numbers alone do not pay
for the plotting stack; scipy is imported inside the functions that use it,
so importing the module does not pay for that either.

The routing runs in this order:

* :func:`classify_cells` sorts every cell into land, sea or void. Sea is
  ground at or below sea level that is joined to the edge of the window,
  or to a missing tile taken as open sea. Low ground inland stays land and
  is filled like any other hollow. A sea area that meets the land along a
  long straight grid line is a gap that a mosaic filled with zeros, not
  sea, so it becomes a void.
* :func:`fill_depressions` raises every hollow to the level at which it
  would spill over, so that every land cell has a way out.
* :func:`flow_directions` sends each land cell to its steepest neighbour
  (D8) on the filled surface.
* :func:`resolve_flats` gives the cells the filling left level a direction
  across the flat, away from higher ground and towards the flat's outlet,
  as Barnes, Lehman and Mulla (2014) describe.
* :func:`accumulate_flow` counts the cells and adds up the area that
  drains through each cell, and flags a cell whose area is uncertain
  because part of what might drain to it lies beyond the window, in a
  void, or in a sea that may be a fill.

What it is not. It traces how water would run over the surface the model
describes, and nothing more. Copernicus GLO-30 is a surface model, with
the tree canopy and the buildings in it, so a line can run along the top
of a forest; a hollow it fills may be a real pond, a quarry or a gap in
the canopy; and it says nothing about where the water table lies or how
groundwater moves beneath. A drainage line is a guide to where to look on
the ground, not a survey of a channel.

Grids are south-first, as :class:`.elevation.ElevationGrid` holds them:
row 0 is the southern edge and north is row + 1. Every scan visits the
eight neighbours in one fixed order, east, south, west, north, then
south-east, south-west, north-west and north-east, and directions are
written as ESRI codes, so a tie between a cardinal and a diagonal
neighbour goes to the cardinal and an exported direction grid reads in any
GIS. The browser's engine in ``docs/js/gwt-core.js`` computes the same
layers with the same operations, in the same order, and the parity suite
holds the two engines to the bit.
"""

from __future__ import annotations

import math

import numpy as np

from .elevation import RowMetric

# --- routing (spec 3.5-3.9)
#
# Integers and copies, never arithmetic that rounds, wherever the browser
# must agree: classes, filled heights, directions, counts and areas are
# compared bit for bit with the browser's engine. Only the D8 drop divides,
# and it is written as the browser writes it.

#: The cell classes held in ``cls`` (uint8). VOID is a cell with no usable
#: height: no data, an implausible value, ground no file supplied, or a
#: sea area found to be a zero-filled gap. SEA includes a missing tile
#: taken as open sea, which has no height at all.
VOID, LAND, SEA = 0, 1, 2

#: The direction code of a land cell that flows out of the analysis: on
#: the edge of the window, or beside a void, with no lower neighbour.
FLOWS_OUT = 255

#: The neighbour order K, the same in every scan and in both engines:
#: E, S, W, N, SE, SW, NW, NE, as (row, column) steps with north = row + 1.
_DR = (0, -1, 0, 1, -1, -1, 1, 1)
_DC = (1, 0, -1, 0, 1, -1, -1, 1)
#: The ESRI code of each direction in K.
_ESRI = (1, 4, 16, 64, 2, 8, 32, 128)
#: Which of the origin row's distances each direction steps: 0 is dx (east
#: or west), 1 is dy (north or south) and 2 is the diagonal dg.
_STEP = (0, 1, 0, 1, 2, 2, 2, 2)
#: Four directions that between them meet every pair of 8-neighbours once.
_HALF = ((0, 1), (1, 0), (1, 1), (1, -1))


def _pair(dr: int, dc: int, rows: int, cols: int) -> tuple[tuple[slice, slice], tuple[slice, slice]]:
    """The two slices that pair each cell with its neighbour ``(dr, dc)``:
    ``a[o]`` holds the cells that have that neighbour inside the grid and
    ``a[n]`` the neighbours, element for element. Views, not copies, so a
    pass over the grid in one direction allocates only its result."""
    o = (slice(max(0, -dr), rows - max(0, dr)), slice(max(0, -dc), cols - max(0, dc)))
    n = (slice(max(0, dr), rows + min(0, dr)), slice(max(0, dc), cols + min(0, dc)))
    return o, n


def _perimeter(rows: int, cols: int) -> np.ndarray:
    """The cells on the edge of the analysed window."""
    edge = np.zeros((rows, cols), dtype=bool)
    edge[0, :] = True
    edge[-1, :] = True
    edge[:, 0] = True
    edge[:, -1] = True
    return edge


def _beside(mask: np.ndarray) -> np.ndarray:
    """Cells with at least one of their eight neighbours in ``mask``."""
    rows, cols = mask.shape
    near = np.zeros((rows, cols), dtype=bool)
    for k in range(8):
        o, n = _pair(_DR[k], _DC[k], rows, cols)
        near[o] |= mask[n]
    return near


def _grid(name: str, a, shape: tuple[int, ...] | None = None) -> np.ndarray:
    """``a`` as an array, refused unless it is a grid of the expected shape."""
    a = np.asarray(a)
    if a.ndim != 2 or (shape is not None and a.shape != shape):
        expected = "a two-dimensional grid" if shape is None else f"a {shape[0]} by {shape[1]} grid"
        raise ValueError(f"{name} must be {expected}, not an array of shape {a.shape}")
    return a


def _long_runs(mask: np.ndarray, n: int) -> np.ndarray:
    """True where a cell of ``mask`` lies in an unbroken run of at least
    ``n`` True cells along its row.

    Each row is padded with a False at both ends, so that one flattened
    difference finds every run's start and end and no run crosses from one
    row into the next.
    """
    rows, cols = mask.shape
    padded = np.zeros((rows, cols + 2), dtype=np.int8)
    padded[:, 1:-1] = mask
    flat = padded.ravel()
    step = np.diff(flat)
    starts = np.flatnonzero(step == 1) + 1
    ends = np.flatnonzero(step == -1) + 1
    long = (ends - starts) >= n
    mark = np.zeros(flat.size, dtype=np.int32)
    mark[starts[long]] = 1
    mark[ends[long]] = -1          # a run ends on a padding or a False cell, never on a start
    inside = np.cumsum(mark) > 0
    return inside.reshape(rows, cols + 2)[:, 1:-1]


def classify_cells(z, sea_level_m: float, assumed_sea=None, straight_edge_cells: int = 150
                   ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Sort every cell into land, sea or void, and find the land cells
    water can leave the land from.

    Returns ``(cls, seed, zero_fill, zt)``:

    ``cls``
        uint8, :data:`VOID`, :data:`LAND` or :data:`SEA`.
    ``seed``
        land cells on the edge of the window or beside sea or a void: the
        places water leaves the land, from which filling starts.
    ``zero_fill``
        the cells of sea areas found to be zero-filled gaps, now voids.
    ``zt``
        the working heights: ``z`` in float64 with any negative zero made
        positive, and NaN on every void and on assumed sea.

    Sea is ground at or below ``sea_level_m`` joined, through other such
    ground and diagonally too, to such a cell on the edge of the window or
    to a cell of ``assumed_sea`` (a missing tile taken as open sea, which
    has no height). Low ground not so joined is an inland hollow: it stays
    land, and the filling raises it. The joining never crosses a void.

    A mosaic made from tiles without a no-data value fills a missing tile
    with 0.0, which would read as a sea about a hundred kilometres inland.
    Real coasts are ragged; the edge of a filled tile is a grid line. So a
    sea area that meets land along a straight row or column for
    ``straight_edge_cells`` cells or more is taken as a gap: every cell of
    it becomes a void, and the cells are returned in ``zero_fill`` so that
    they can be counted. The edges of assumed sea are not counted, because
    a missing tile's edge is straight by nature.
    """
    from scipy import ndimage

    zt = np.add(np.asarray(_grid("z", z), dtype=np.float64), 0.0)   # -0 becomes +0
    rows, cols = zt.shape
    if assumed_sea is None:
        assumed = np.zeros((rows, cols), dtype=bool)
    else:
        assumed = _grid("assumed_sea", assumed_sea, (rows, cols)).astype(bool)
        zt[assumed] = np.nan          # assumed sea has no height, whatever was passed
    finite = np.isfinite(zt)
    with np.errstate(invalid="ignore"):
        low = finite & (zt <= sea_level_m)
    cand = low | assumed
    labels = np.zeros((rows, cols), dtype=np.int32)
    ndimage.label(cand, structure=np.ones((3, 3), dtype=bool), output=labels)
    count = int(labels.max(initial=0))
    edge = _perimeter(rows, cols)
    joined = np.zeros(count + 1, dtype=bool)
    joined[labels[edge]] = True
    joined[labels[assumed]] = True
    joined[0] = False
    sea0 = joined[labels]
    land = finite & ~sea0
    sea0f = finite & sea0

    # Where sea meets land across a row boundary (hb) or a column boundary
    # (vb), the runs along that boundary; a long one condemns the sea area
    # that owns its sea side.
    gap = np.zeros(count + 1, dtype=bool)
    if rows > 1:
        hb = (sea0f[:-1, :] & land[1:, :]) | (land[:-1, :] & sea0f[1:, :])
        long = _long_runs(hb, straight_edge_cells)
        gap[labels[:-1, :][long & sea0f[:-1, :]]] = True
        gap[labels[1:, :][long & sea0f[1:, :]]] = True
    if cols > 1:
        vb = (sea0f[:, :-1] & land[:, 1:]) | (land[:, :-1] & sea0f[:, 1:])
        long = _long_runs(vb.T, straight_edge_cells).T
        gap[labels[:, :-1][long & sea0f[:, :-1]]] = True
        gap[labels[:, 1:][long & sea0f[:, 1:]]] = True
    gap[0] = False
    zero_fill = gap[labels]

    cls = np.zeros((rows, cols), dtype=np.uint8)
    cls[land] = LAND
    cls[sea0 & ~zero_fill] = SEA
    zt[cls == VOID] = np.nan
    seed = land & (edge | _beside(~land))
    return cls, seed, zero_fill, zt


def _basin_roots(zt: np.ndarray, land: np.ndarray, seed: np.ndarray) -> np.ndarray:
    """For every cell, the node its descent ends at: a land cell from which
    there is no way down (the bottom of a hollow, or one cell of a level
    hollow floor), or ``rows * cols``, the node OUT, for every cell that
    descends to a seed. Seeds and every cell that is not land go to OUT.

    Each land cell points to the neighbour it drops most to; with none
    lower, to a neighbour of the same height that comes earlier in the
    grid, so that a level floor gathers into a few basins rather than one
    per cell (the pointers cannot go round in a circle, because each step
    goes down or goes back in the grid). The filled surface does not depend
    on how the basins are drawn, only on every cell having a path within
    its basin to the basin's root that never climbs above the cell.
    """
    rows, cols = zt.shape
    size = rows * cols
    index = np.arange(size, dtype=np.int64).reshape(rows, cols)
    target = index.copy()
    best = np.zeros((rows, cols))
    with np.errstate(invalid="ignore"):
        for k in range(8):
            o, n = _pair(_DR[k], _DC[k], rows, cols)
            drop = zt[o] - zt[n]
            better = drop > best[o]
            np.copyto(best[o], drop, where=better)
            np.copyto(target[o], index[n], where=better)
        level = land & ~seed & (best == 0.0)
        for k in (1, 2, 4, 5):          # S, W, SE, SW: the neighbours earlier in the grid
            o, n = _pair(_DR[k], _DC[k], rows, cols)
            same = level[o] & (zt[n] == zt[o])
            np.copyto(target[o], index[n], where=same)
            level[o] &= ~same
    pointer = np.empty(size + 1, dtype=np.int64)
    pointer[:size] = target.ravel()
    pointer[size] = size
    pointer[:size][(seed | ~land).ravel()] = size
    while True:
        jumped = pointer[pointer]
        if np.array_equal(jumped, pointer):
            return pointer[:size]
        pointer = jumped


def fill_depressions(zt, cls, seed) -> np.ndarray:
    """The filled surface: every land cell raised to the lowest level at
    which water standing on it could reach a seed.

    For each land cell this is the least, over all paths through land to a
    seed, of the highest cell on the path, the seed included. Seeds keep
    their height. Sea keeps its own height (NaN on assumed sea) and a void
    is NaN. The result only ever copies heights that are already there, so
    once a negative zero has been made positive, as :func:`classify_cells`
    does, any correct method gives the same bits; the browser uses
    Priority-Flood.

    The method here is the basin graph, because a loop over every cell
    would be far too slow in Python: each land cell is put in the basin it
    descends to; neighbouring basins are joined at the lower of their
    highest shared heights; and the level each basin spills at is found on
    the basins alone (a few per cent of the cells). A cell's filled height
    is its own height or its basin's spill level, whichever is higher.
    """
    zt = np.asarray(_grid("zt", zt), dtype=np.float64)
    shape = zt.shape
    cls = _grid("cls", cls, shape)
    seed = _grid("seed", seed, shape).astype(bool)
    rows, cols = shape
    size = rows * cols
    land = cls == LAND
    if not land.any():
        filled = zt.copy()
        filled[cls == VOID] = np.nan
        return filled

    roots = _basin_roots(zt, land, seed)
    # Basin numbers: 0 is OUT, then each root in grid order.
    number = np.full(size + 1, -1, dtype=np.int64)
    number[size] = 0
    root_cells = np.flatnonzero(roots == np.arange(size))
    number[root_cells] = np.arange(1, root_cells.size + 1)
    basins = root_cells.size + 1
    basin = number[roots].reshape(rows, cols)

    # The pass between two basins is the lowest of the higher heights of
    # the pairs of land cells that join them.
    keys, weights = [], []
    for dr, dc in _HALF:
        o, n = _pair(dr, dc, rows, cols)
        a, b = basin[o], basin[n]
        meet = land[o] & land[n] & (a != b)
        a, b = a[meet], b[meet]
        keys.append(np.minimum(a, b) * basins + np.maximum(a, b))
        weights.append(np.maximum(zt[o][meet], zt[n][meet]))
    key = np.concatenate(keys)
    weight = np.concatenate(weights)
    spill = np.full(basins, math.inf)
    spill[0] = -math.inf
    if key.size:
        order = np.argsort(key)
        key = key[order]
        first = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
        passes = np.minimum.reduceat(weight[order], first)
        lo, hi = np.divmod(key[first], basins)
        spill = _spill_levels(basins, lo, hi, passes)
    # Every cell that is not land is in basin 0, whose level is -inf, so
    # it keeps its own height; done over the whole grid, because picking
    # out the land cells costs more than the arithmetic.
    filled = np.maximum(zt, spill[basin])
    filled[cls == VOID] = np.nan
    return filled


def _spill_levels(basins: int, lo: np.ndarray, hi: np.ndarray, passes: np.ndarray) -> np.ndarray:
    """The level at which each basin spills: the least, over every chain of
    passes from basin 0 (OUT) to it, of the highest pass on the chain.

    Found on a minimum spanning tree of the basin graph, whose path from
    OUT to each basin is such a least chain (the minimax property of every
    minimum spanning tree), by pointer doubling up the tree. The answer is
    one of the passes' own heights, so it is the same as a minimax search
    with a heap would give, and is found by compiled code rather than a
    Python loop over every basin. A basin no chain reaches spills at
    infinity, which only a call without seeds can produce.
    """
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import breadth_first_order, minimum_spanning_tree

    # The tree is built on the passes' ranks, not their heights: csgraph
    # takes a weight of zero for a missing edge, and a pass can be at 0 m
    # or below it. Ranks keep the order, and the order is all a minimum
    # spanning tree depends on.
    by_height = np.argsort(passes, kind="stable")
    rank = np.empty(passes.size)
    rank[by_height] = np.arange(1, passes.size + 1)
    tree = minimum_spanning_tree(csr_matrix((rank, (lo, hi)), shape=(basins, basins)))
    tree = (tree + tree.T).tocoo()
    _, parent = breadth_first_order(tree.tocsr(), 0, directed=True, return_predecessors=True)
    parent = parent.astype(np.int64)
    reached = parent >= 0
    up = np.full(basins, math.inf)            # the highest pass between a basin and anc
    up[0] = -math.inf
    to_parent = parent[tree.col] == tree.row
    child = tree.col[to_parent]
    up[child] = passes[by_height[tree.data[to_parent].astype(np.int64) - 1]]
    anc = np.where(reached, parent, np.arange(basins))
    while True:
        up = np.maximum(up, up[anc])
        nxt = anc[anc]
        if np.array_equal(nxt, anc):
            return up
        anc = nxt


def flow_directions(zt, filled, cls, seed, metric: RowMetric, sea_level_m: float) -> np.ndarray:
    """D8 directions on the filled surface, as ESRI codes (uint8).

    Each land cell flows to the neighbour with the steepest drop, the drop
    in height divided by the distance between the cell centres in the
    cell's own row. A land neighbour offers its filled height, a sea
    neighbour its own height, and assumed sea, which has none, sea level.
    A void is never a neighbour. A drop must be strictly the steepest to
    win, so of equal drops the first in the order E, S, W, N, SE, SW, NW,
    NE is taken, and a cardinal neighbour beats a diagonal one.

    A land cell with no drop at all is 0, unless it is a seed, which flows
    out of the analysis (:data:`FLOWS_OUT`, 255). Cells that are not land
    are 0. The cells left at 0 lie on flats, which :func:`resolve_flats`
    routes.
    """
    filled = np.asarray(_grid("filled", filled), dtype=np.float64)
    shape = filled.shape
    zt = np.asarray(_grid("zt", zt, shape), dtype=np.float64)
    cls = _grid("cls", cls, shape)
    seed = _grid("seed", seed, shape).astype(bool)
    rows, cols = shape
    land = cls == LAND
    void = cls == VOID
    offer = np.where(land, filled, np.where(np.isfinite(zt), zt, sea_level_m))
    dist = (np.asarray(metric.dx, dtype=np.float64), np.asarray(metric.dy, dtype=np.float64),
            np.asarray(metric.dg, dtype=np.float64))
    if any(d.shape != (rows,) for d in dist):
        raise ValueError(f"the metric must have one distance per row ({rows})")
    best = np.zeros(shape)
    code = np.zeros(shape, dtype=np.uint8)
    with np.errstate(invalid="ignore"):
        for k in range(8):
            o, n = _pair(_DR[k], _DC[k], rows, cols)
            drop = (filled[o] - offer[n]) / dist[_STEP[k]][o[0]][:, None]
            better = land[o] & ~void[n] & (drop > best[o])
            np.copyto(best[o], drop, where=better)
            code[o][better] = _ESRI[k]
    code[land & (code == 0) & seed] = FLOWS_OUT
    return code


def _padded(a: np.ndarray, fill) -> np.ndarray:
    """``a`` with a border of one ``fill`` cell, flattened, so that the
    neighbours of a cell at flat index ``i`` are at ``i + offset`` with no
    test for the edge of the grid."""
    rows, cols = a.shape
    out = np.full((rows + 2, cols + 2), fill, dtype=a.dtype)
    out[1:-1, 1:-1] = a
    return out.ravel()


def _flat_levels(table: np.ndarray, onto: np.ndarray, from_higher: np.ndarray, from_outlets: np.ndarray
                 ) -> tuple[np.ndarray, np.ndarray]:
    """The two breadth-first levels of the flats: 1 at the seeds, one more
    for each step, 0 where no seed reaches. Node ``i`` steps to
    ``table[i, k]`` wherever ``onto[i, k]``; the steps from higher ground
    start at the nodes ``from_higher``, those towards the outlets at
    ``from_outlets``.

    One graph serves both searches, each from a virtual node of its own
    joined to its seeds. No step leads onto an outlet, so the search from
    higher ground never sets foot on one and never uses the steps out of
    one, which only the other search needs. csgraph's search builds a tree
    holding each node at its least number of steps from a seed, and the
    level is that depth, counted by pointer doubling up the tree.
    """
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import breadth_first_order

    nodes = table.shape[0]
    indptr = np.zeros(nodes + 3, dtype=np.int32)
    np.cumsum(onto.sum(axis=1), out=indptr[1:nodes + 1])
    indptr[nodes + 1] = indptr[nodes] + from_higher.size
    indptr[nodes + 2] = indptr[nodes + 1] + from_outlets.size
    indices = np.concatenate([table[onto], from_higher, from_outlets]).astype(np.int32, copy=False)
    graph = csr_matrix((np.ones(indices.size), indices, indptr), shape=(nodes + 2, nodes + 2))
    levels = []
    for source in (nodes, nodes + 1):
        _, parent = breadth_first_order(graph, source, directed=True, return_predecessors=True)
        reached = parent >= 0
        depth = reached.astype(np.int64)          # steps from a node up to anc
        anc = np.where(reached, parent, source)
        while True:
            depth += depth[anc]
            nxt = anc[anc]
            if np.array_equal(nxt, anc):
                break
            anc = nxt
        levels.append(depth[:nodes])
    return levels[0], levels[1]


def resolve_flats(filled, cls, code_d8) -> tuple[np.ndarray, int]:
    """Directions across the flats the D8 pass left at 0, by the method of
    Barnes, Lehman and Mulla (2014), with one constant for the whole grid
    in place of each flat's own height.

    A flat is drained by a gradient that is the sum of two breadth-first
    distances: towards the flat's outlets (the flowing cells beside it at
    its height, counted twice so that it dominates) and away from the
    higher ground around it, so that water crosses a flat down its middle
    rather than along its edge. With ``A`` the distance from higher ground
    (0 where it does not reach), ``T`` the distance from the outlets, and
    ``K`` the largest ``A`` anywhere, a cell's mask is ``(K - A) + 2T``, or
    ``2T`` where ``A`` is 0. Within one flat ``K`` differs from Barnes's
    per-flat height by a constant, so every direction is the same as his.
    Each flat cell flows to its neighbour at the same height with the
    smallest mask below its own, the first in the scan order on ties.

    Returns the directions and the number of flat cells left without one,
    which after :func:`fill_depressions` is always 0.
    """
    filled = np.asarray(_grid("filled", filled), dtype=np.float64)
    shape = filled.shape
    cls = _grid("cls", cls, shape)
    code = np.array(_grid("code_d8", code_d8, shape), dtype=np.uint8, copy=True)
    rows, cols = shape
    land = cls == LAND
    noflow = land & (code == 0)
    if not noflow.any():
        return code, 0

    # Flat indices into the grid with a border of one cell, so that the
    # work is done on the flat cells and the cells beside them alone.
    wide = cols + 2
    offset = [_DR[k] * wide + _DC[k] for k in range(8)]
    height = _padded(filled, np.nan)
    is_land = _padded(land, False)
    is_flat = _padded(noflow, False)
    flowing = is_land & ~is_flat
    flat = np.flatnonzero(is_flat)
    at = height[flat]
    high = np.zeros(flat.size, dtype=bool)   # flat cells beside higher land
    is_node = is_flat.copy()                 # flat cells, and the outlets beside them
    with np.errstate(invalid="ignore"):
        for k in range(8):
            j = flat + offset[k]
            high |= is_land[j] & (height[j] > at)
            is_node[j[flowing[j] & (height[j] == at)]] = True
    cells = np.flatnonzero(is_node)
    nodes = cells.size
    node = np.full(is_node.size, -1, dtype=np.int32)
    node[cells] = np.arange(nodes, dtype=np.int32)
    outlets = node[cells[~is_flat[cells]]]

    # Each node's neighbours at its own height (all of them flat cells or
    # outlets); a search steps only onto a flat cell.
    level = height[cells]
    table = np.empty((nodes, 8), dtype=np.int32)
    same = np.empty((nodes, 8), dtype=bool)
    onto = np.empty((nodes, 8), dtype=bool)
    with np.errstate(invalid="ignore"):
        for k in range(8):
            j = cells + offset[k]
            table[:, k] = node[j]
            same[:, k] = (node[j] >= 0) & (height[j] == level)
            onto[:, k] = same[:, k] & is_flat[j]
    on_flat = is_flat[cells]
    away, towards = _flat_levels(table, onto, node[flat[high]], outlets)
    top = int(away.max())
    mask = np.where(away > 0, (top - away) + 2 * towards, 2 * towards)

    mine = np.flatnonzero(on_flat)
    best = mask[mine]
    step = np.full(mine.size, -1, dtype=np.int64)
    for k in range(8):
        there = table[mine, k]
        better = same[mine, k] & (mask[there] < best)
        best = np.where(better, mask[there], best)
        step = np.where(better, k, step)
    where = cells[mine]
    grid_index = (where // wide - 1) * cols + (where % wide - 1)
    done = step >= 0
    np.put(code, grid_index[done], np.asarray(_ESRI, dtype=np.uint8)[step[done]])
    return code, int(np.count_nonzero(~done))


def accumulate_flow(code, cls, metric: RowMetric, sea_clean: bool
                    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The cells and the area draining through every land cell, and
    whether that area is uncertain.

    Returns ``(count, area_units, flag)``. ``count`` counts the cell
    itself, as TauDEM and Whitebox do (ESRI's flow accumulation is one
    less). ``area_units`` is in whole units of 0.01 square metres, the
    rows' ``au_row``, so that sums are exact in any order: a float sum of
    the same areas moves in the last bits when the order does. Both are
    int64; cells that are not land hold 0.

    ``flag`` is TauDEM's edge-contamination rule, marking cells rather than
    deleting them: a cell is flagged when it lies on the edge of the window
    or beside a void, or beside sea when the source is not known to write
    sea as 0 m (``sea_clean`` False, where an undetected 0 m fill might be
    land), or when any cell draining to it is flagged. A flagged area may
    be short, because ground beyond the edge or in the void may drain here,
    or long, because ground counted here may drain elsewhere in truth.

    A cell drains to the land neighbour its code points to; a code
    pointing at sea, a void or out of the analysis ends the path there.
    """
    code = _grid("code", code)
    shape = code.shape
    cls = _grid("cls", cls, shape)
    rows, cols = shape
    size = rows * cols
    au_row = np.asarray(metric.au_row, dtype=np.int64)
    if au_row.shape != (rows,):
        raise ValueError(f"the metric must have one area per row ({rows})")
    land = cls == LAND
    index = np.arange(size, dtype=np.int64).reshape(shape)
    down = np.full(shape, -1, dtype=np.int64)
    for k in range(8):
        o, n = _pair(_DR[k], _DC[k], rows, cols)
        np.copyto(down[o], index[n], where=land[o] & (code[o] == _ESRI[k]) & land[n])
    down = down.ravel()

    count = land.astype(np.int64).ravel()
    area = np.where(land, au_row[:, None], 0).astype(np.int64).ravel()
    risky = _perimeter(rows, cols) | _beside(cls == VOID)
    if not sea_clean:
        risky |= _beside(cls == SEA)
    flag = (land & risky).ravel()

    # Kahn's order in waves: every cell with nothing left to receive passes
    # its totals on at once, grouped by the cell they go to.
    has = down >= 0
    inflow = np.bincount(down[has], minlength=size)
    front = np.flatnonzero(has & (inflow == 0) & land.ravel())
    while front.size:
        to = down[front]
        order = np.argsort(to)
        to = to[order]
        front = front[order]
        first = np.flatnonzero(np.r_[True, to[1:] != to[:-1]])
        u = to[first]
        count[u] += np.add.reduceat(count[front], first)
        area[u] += np.add.reduceat(area[front], first)
        flag[u] |= np.logical_or.reduceat(flag[front], first)
        inflow[u] -= np.diff(np.r_[first, to.size])
        front = u[(inflow[u] == 0) & has[u]]
    return count.reshape(shape), area.reshape(shape), flag.reshape(shape)

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

:func:`analyse_terrain` runs these on a window together with the surface
kernels (slope, shading, the wetness index and curvature), traces the
drainage lines (:func:`drainage_links`), cuts them to the square shown and
sums that square up; :func:`terrain_captions` and :func:`drainage_geojson`
write what the figures and the drainage lines' download say.

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

import json
import math
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np

from ..config import TerrainConfig
from ..text import phrase
from ..utils import and_join
from .elevation import ElevationGrid, ElevationRead, RowMetric, row_metric, sin_cos_deg

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
    if not (rows and cols):
        # A grid with no cells has no edge. Both engines route it to empty
        # layers rather than refusing it.
        return edge
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


def classify_cells(z, sea_level_m: float, assumed_sea=None, straight_edge_cells: int | None = 150
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
    ``straight_edge_cells`` cells or more (150 when None) is taken as a
    gap: every cell of it becomes a void, and the cells are returned in
    ``zero_fill`` so that they can be counted. The edges of assumed sea
    are not counted, because a missing tile's edge is straight by nature.
    """
    from scipy import ndimage

    if straight_edge_cells is None:
        # None means the default, as null or a value left out does in the
        # browser's classifyCells
        straight_edge_cells = 150
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
    if any(d.shape != (rows,) for d in dist):     # refused in both engines, as in every kernel with a metric
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


def _flat_steps(k: int, cells: np.ndarray, level: np.ndarray, node: np.ndarray, height: np.ndarray,
                is_flat: np.ndarray, offset: Sequence[int]) -> tuple[np.ndarray, np.ndarray]:
    """The neighbour in direction ``k`` of each node at padded index
    ``cells``, as a node number (-1 where it is none), and whether a search
    steps onto it: a flat cell at the node's own height ``level``."""
    j = cells + offset[k]
    there = node[j]
    with np.errstate(invalid="ignore"):
        onto = (there >= 0) & (height[j] == level) & is_flat[j]
    return there, onto


def _flat_graph(node: np.ndarray, height: np.ndarray, is_flat: np.ndarray, offset: Sequence[int],
                from_higher: np.ndarray, from_outlets: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The graph the flats are searched on, in compressed rows (``indptr``
    and ``indices``, int32): row ``i`` lists the nodes node ``i`` steps
    to, in the order K, and two more rows are the virtual nodes the
    searches start from, joined to ``from_higher`` and to the outlets.

    It is written in place, a direction at a time, so that no table of
    eight neighbours per node is held: a 2-million-cell flat would hold
    several of them, at once, beside the graph itself.
    """
    cells = np.flatnonzero(node >= 0)            # the nodes, in their order
    level = height[cells]
    nodes = cells.size
    indptr = np.zeros(nodes + 3, dtype=np.int32)
    degree = indptr[1:nodes + 1]
    for k in range(8):
        degree += _flat_steps(k, cells, level, node, height, is_flat, offset)[1]
    np.cumsum(degree, out=degree)
    indptr[nodes + 1] = indptr[nodes] + from_higher.size
    indptr[nodes + 2] = indptr[nodes + 1] + from_outlets.size
    indices = np.empty(int(indptr[nodes + 2]), dtype=np.int32)
    fill = indptr[:nodes].copy()                 # where each row's next step goes
    for k in range(8):
        there, onto = _flat_steps(k, cells, level, node, height, is_flat, offset)
        at = np.flatnonzero(onto)
        indices[fill[at]] = there[at]
        fill[at] += 1
    indices[indptr[nodes]:indptr[nodes + 1]] = from_higher
    indices[indptr[nodes + 1]:] = from_outlets
    return indptr, indices


def _flat_levels(node: np.ndarray, height: np.ndarray, is_flat: np.ndarray, offset: Sequence[int],
                 from_higher: np.ndarray, from_outlets: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The two breadth-first levels of the flats on the graph
    :func:`_flat_graph` writes (int32, by node): 1 at the seeds, one more
    for each step, 0 where no seed reaches; the first from higher ground,
    the second towards the outlets.

    One graph serves both searches, each from a virtual node of its own
    joined to its seeds. No step leads onto an outlet, so the search from
    higher ground never sets foot on one and never uses the steps out of
    one, which only the other search needs. csgraph's search builds a tree
    holding each node at its least number of steps from a seed, and the
    level is that depth, counted by pointer doubling up the tree once the
    graph has been let go.
    """
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import breadth_first_order

    indptr, indices = _flat_graph(node, height, is_flat, offset, from_higher, from_outlets)
    nodes = indptr.size - 3
    # csgraph searches a float64 matrix and would copy any other data into
    # one; the values themselves are never read.
    graph = csr_matrix((np.ones(indices.size), indices, indptr), shape=(nodes + 2, nodes + 2))
    del indptr, indices
    sources = (nodes, nodes + 1)
    parents = [breadth_first_order(graph, source, directed=True, return_predecessors=True)[1] for source in sources]
    del graph
    levels = []
    for source, parent in zip(sources, parents, strict=True):
        reached = parent >= 0
        depth = reached.astype(np.int32)          # steps from a node up to anc
        anc = np.where(reached, parent, source)
        del reached
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
    from_higher = node[flat[high]]
    del is_land, flowing, flat, at, high, is_node, cells

    # Each node's neighbours at its own height (all of them flat cells or
    # outlets); a search steps only onto a flat cell.
    away, towards = _flat_levels(node, height, is_flat, offset, from_higher, outlets)
    top = int(away.max())
    towards = 2 * towards.astype(np.int64)
    mask = np.where(away > 0, (top - away) + towards, towards)
    del away, towards

    # Each flat cell takes the neighbour at its height with the smallest
    # mask below its own.
    flat = np.flatnonzero(is_flat)
    here = height[flat]
    best = mask[node[flat]]
    step = np.full(flat.size, -1, dtype=np.int8)
    with np.errstate(invalid="ignore"):
        for k in range(8):
            j = flat + offset[k]
            there = node[j]
            better = (there >= 0) & (height[j] == here) & (mask[there] < best)
            best = np.where(better, mask[there], best)
            step = np.where(better, k, step)
    grid_index = (flat // wide - 1) * cols + (flat % wide - 1)
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
    given = np.asarray(metric.au_row)
    if given.shape != (rows,):
        raise ValueError(f"the metric must have one area per row ({rows})")
    # Both engines refuse a cell area that is not a whole number of units,
    # or so large that the largest times the cells reaches 2**53: cast to
    # int64 here a fraction would be cut off that the browser's Float64Array
    # keeps, and past 2**53 its totals would round where these are exact.
    whole = given.astype(np.float64)
    if not (np.all(np.isfinite(whole) & (whole >= 0.0) & (whole == np.floor(whole)))
            and float(whole.max(initial=0.0)) * size < 2.0**53):
        raise ValueError("the metric's cell areas must be whole units of 0.01 m2, "
                         "the largest times the number of cells below 2**53")
    au_row = given.astype(np.int64)
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


# --- analysis (spec 3.10, 3.15, 4.1)
#
# The routing and the surface run together on one window: the drainage
# lines traced from the routing, cut to the square shown, the summary of
# that square, the captions and the drainage lines' GeoJSON. Every count,
# threshold, line and limit is taken from integers or from float64 layers;
# the float32 copies that precision="float32" keeps are pictures, narrowed
# after everything has been read from them. The browser's engine assembles
# the same pieces in the same order, and drainage_links runs there again on
# the page, from the core alone, whenever the threshold changes.

#: The ESRI direction codes as an index into the neighbour order K: -1 for
#: a code that is not a direction (0, a flat; 255, out of the analysis).
_K_OF_CODE = np.full(256, -1, dtype=np.int64)
_K_OF_CODE[list(_ESRI)] = np.arange(8)


@dataclass(frozen=True, eq=False)
class TerrainCore:
    """The layers a drainage line is traced from, and nothing more.

    The browser's worker hands this much to the page, so that a new
    drainage threshold re-traces the lines without running the analysis
    again; :func:`drainage_links` takes the same here, so both apps trace
    from the same inputs with the same function.

    ``rows`` and ``cols`` are the size of the analysed grid and ``shown``
    the square shown, as rows ``r0:r1`` and columns ``c0:c1`` of it.
    ``lons`` and ``lats`` are the cell centres (``lats`` from the south),
    ``dx``, ``dy`` and ``dg`` each row's cell sizes in metres. ``cls`` and
    ``code`` are the classes and the directions after the flats (uint8).
    ``flag``, ``raised`` and ``flat_routed`` are masks: the upslope area is
    uncertain, the fill raised the cell by ``fill_note_m`` or more, and the
    cell was routed across a flat or a filled hollow rather than by its
    slope. ``count`` and ``area_units`` are the cells and the area, in whole
    0.01 m² units, draining through each cell (int64).
    """

    rows: int
    cols: int
    shown: tuple[int, int, int, int]
    lons: np.ndarray = field(repr=False)
    lats: np.ndarray = field(repr=False)
    dx: np.ndarray = field(repr=False)
    dy: np.ndarray = field(repr=False)
    dg: np.ndarray = field(repr=False)
    cls: np.ndarray = field(repr=False)
    code: np.ndarray = field(repr=False)
    flag: np.ndarray = field(repr=False)
    raised: np.ndarray = field(repr=False)
    flat_routed: np.ndarray = field(repr=False)
    count: np.ndarray = field(repr=False)
    area_units: np.ndarray = field(repr=False)


@dataclass(frozen=True)
class DrainageLink:
    """One drainage line over the whole analysed square, from where it
    starts (a headwater, or the cell where two lines meet) to where it
    ends: where it meets another line, the sea, a void or the edge.

    ``start`` is the flat index of its first cell. ``vertices`` are
    ``(row, column)`` cells of the analysed grid: the first, every cell
    where the line turns or changes how it was routed, and the last
    position, which is the cell the line runs into (the first cell of the
    line it joins, or the sea cell) where it runs into one. Nothing between
    two vertices is lost: the cells between them run straight, routed one
    way. ``cells`` counts the line's own cells; ``length_m`` is the length
    along them, the step into that last position included.

    ``area_units`` and ``edge_contaminated`` are those of the line's last
    own cell. ``filled_cells`` and ``flat_routed_cells`` count its own
    cells raised by ``fill_note_m`` or more by the fill, and routed across
    a flat or a filled hollow rather than by slope. ``downstream`` is the
    id of the line it joins, or -1; ``strahler`` its Strahler order.
    """

    id: int
    start: int
    vertices: tuple[tuple[int, int], ...]
    cells: int
    outlet: str
    downstream: int
    strahler: int
    area_units: int
    length_m: float
    edge_contaminated: bool
    filled_cells: int
    flat_routed_cells: int


@dataclass(frozen=True)
class DrainagePart:
    """The piece of a drainage line inside the square shown: what both apps
    draw and the GeoJSON exports.

    A line that leaves the square and comes back is cut into parts,
    numbered from 0 along it (``part``); a piece of a single cell is not
    drawn and takes no number. ``vertices`` follow the rule of
    :class:`DrainageLink` over the piece, and ``stretch_flat[v]`` says
    whether the stretch from vertex ``v`` to the next was routed across a
    flat or a filled hollow, so that it can be drawn paler. ``outlet`` is
    the line's own where the piece holds the line's end, else
    ``"beyond_view"``. ``area_units``, ``edge_contaminated``,
    ``filled_cells`` and ``flat_routed_cells`` are taken over the piece's
    own cells as :class:`DrainageLink` takes them over the line's.
    """

    id: int
    part: int
    vertices: tuple[tuple[int, int], ...]
    stretch_flat: tuple[bool, ...]
    outlet: str
    strahler: int
    downstream: int
    area_units: int
    length_m: float
    edge_contaminated: bool
    filled_cells: int
    flat_routed_cells: int


@dataclass(frozen=True, eq=False)
class TerrainAnalysis:
    """Everything worked out from one window, for the figures, the
    downloads and the hand-over to lineament work (PLAN.md step 4.2).

    ``grid`` is the window analysed and ``metric`` its row metric; ``core``
    the layers the drainage lines are traced from (:class:`TerrainCore`).
    ``filled`` is the filled surface and ``fill_depth`` how far the fill
    raised each land cell (NaN elsewhere); ``unresolved`` counts the flat
    cells left without a direction, which is always 0. ``stream`` marks the
    cells at or above the drainage threshold, ``links`` the drainage lines
    over the analysed square and ``parts`` their pieces in the square shown.

    ``p`` and ``q`` are the Horn gradients, always in float64, and ``tanb``
    the slope. ``hillshades`` are lit from the panel azimuths, in their
    order, and ``hillshade_multi`` is the composite. ``twi_arg`` is the
    wetness index's exact argument, always in float64, and ``twi`` its
    logarithm. ``profile`` and ``tangential`` are the curvatures, sampled
    ``k_cells`` apart. ``floored`` and ``zero_fill`` count, over the square
    shown as the summary does, the cells whose slope the wetness index
    floored and the cells of zero-filled gaps. ``summary`` holds the counts,
    shares and display limits of the square shown, and ``settings`` the
    configuration the window was analysed with.
    """

    grid: ElevationGrid = field(repr=False)
    metric: RowMetric = field(repr=False)
    core: TerrainCore
    filled: np.ndarray = field(repr=False)
    fill_depth: np.ndarray = field(repr=False)
    unresolved: int
    stream: np.ndarray = field(repr=False)
    links: tuple[DrainageLink, ...] = field(repr=False)
    parts: tuple[DrainagePart, ...] = field(repr=False)
    p: np.ndarray = field(repr=False)
    q: np.ndarray = field(repr=False)
    tanb: np.ndarray = field(repr=False)
    hillshades: tuple[np.ndarray, ...] = field(repr=False)
    hillshade_multi: np.ndarray = field(repr=False)
    twi_arg: np.ndarray = field(repr=False)
    twi: np.ndarray = field(repr=False)
    profile: np.ndarray = field(repr=False)
    tangential: np.ndarray = field(repr=False)
    k_cells: int
    floored: int
    zero_fill: int
    summary: dict
    settings: TerrainConfig


def _threshold_units(area_km2: float) -> int:
    """The drainage threshold in whole 0.01 m² units, rounded half up: 0.5
    km² is 5e7 units, about 532 cells at 8.5 degrees north and 1
    arc-second. Areas are compared as integers, so a cell is a stream cell
    in both engines or in neither."""
    area = float(area_km2)
    if not (math.isfinite(area) and area >= 0.0):
        raise ValueError(f"the drainage area must be a number of square kilometres, not {area_km2!r}")
    return math.floor(area * 1e8 + 0.5)


def _vertex_positions(turns: Sequence[int], a: int, b: int) -> list[int]:
    """The positions ``a`` to ``b - 1`` of a line kept as vertices: both
    ends, and every position between them in ``turns`` (where the line
    turns or changes how it was routed). One position is one vertex."""
    if b - a == 1:
        return [a]
    return [a, *(m for m in turns if a < m < b - 1), b - 1]


def _summed(steps: Sequence[float]) -> float:
    """``steps`` added one after another, as the browser adds them. Python's
    ``sum`` of floats compensates for rounding (3.12 on), so it can give
    other bits than a plain loop."""
    total = 0.0
    for step in steps:
        total += step
    return total


def drainage_links(core: TerrainCore, area_km2: float
                   ) -> tuple[tuple[DrainageLink, ...], tuple[DrainagePart, ...]]:
    """The drainage lines where more than ``area_km2`` drains, over the
    analysed square, and their parts in the square shown.

    A stream cell is a land cell with at least the threshold's area. A line
    starts at every stream cell no other stream cell drains to (a
    headwater) and at every one that two or more drain to (a confluence),
    numbered in grid order, and follows the directions until it meets the
    next confluence, which starts another line, or leaves the land: into
    the sea, which it runs into, or out of the analysis at the edge or at
    a void. Strahler orders are worked out upstream first: a line no other
    line joins is of order 1, and a line is one order higher than the
    highest that joins it only where two or more of that order meet.

    Each line is then cut to the square shown, so that what is drawn and
    exported ends at the edge of the map rather than in the margin, while
    its area, flag and order are still those worked out over the whole
    analysed square. Only integers and comparisons decide the lines, and
    lengths are added in order along them, so both engines trace the same
    lines to the bit; a new threshold needs nothing but the core.
    """
    rows, cols = int(core.rows), int(core.cols)
    r0, r1, c0, c1 = (int(v) for v in core.shown)
    threshold = _threshold_units(area_km2)
    code_flat = np.asarray(core.code, dtype=np.uint8).ravel()
    land = np.asarray(core.cls).ravel() == LAND
    area_flat = np.asarray(core.area_units, dtype=np.int64).ravel()
    cells = np.flatnonzero(land & (area_flat >= threshold))
    if cells.size == 0:
        return (), ()

    # Every stream cell's neighbour along its direction. A stream cell's
    # area only grows downstream, so a land neighbour is a stream cell too;
    # anything else means the core's layers do not belong together.
    row = cells // cols
    col = cells - row * cols
    k = _K_OF_CODE[code_flat[cells]]
    steps = k >= 0
    kk = np.where(steps, k, 0)
    next_row = row + np.asarray(_DR)[kk]
    next_col = col + np.asarray(_DC)[kk]
    in_grid = (next_row >= 0) & (next_row < rows) & (next_col >= 0) & (next_col < cols)
    if (steps & ~in_grid).any():
        raise ValueError("a direction in the core points out of the grid")
    after = np.where(steps, next_row * cols + next_col, 0)
    onto_land = steps & land[after]
    down = np.searchsorted(cells, after)
    down = np.minimum(down, cells.size - 1)
    if (onto_land & (cells[down] != after)).any():
        raise ValueError("a stream cell drains to land below the threshold; the core's layers disagree")
    down = np.where(onto_land, down, -1)
    feeds = np.bincount(down[down >= 0], minlength=cells.size)

    dist = np.zeros(cells.size)
    for step, sizes in enumerate((core.dx, core.dy, core.dg)):
        which = steps & (np.asarray(_STEP)[kk] == step)
        dist[which] = np.asarray(sizes, dtype=np.float64)[row[which]]
    edge = (row == 0) | (row == rows - 1) | (col == 0) | (col == cols - 1)

    # The loop below walks the stream cells alone, by their position in
    # ``cells``, on plain lists: a few per cent of the grid.
    down_l = down.tolist()
    feeds_l = feeds.tolist()
    code_l = code_flat[cells].tolist()
    row_l, col_l = row.tolist(), col.tolist()
    next_l = list(zip(next_row.tolist(), next_col.tolist(), strict=True))
    dist_l = dist.tolist()
    edge_l = edge.tolist()
    flat_l = np.asarray(core.flat_routed, dtype=bool).ravel()[cells].tolist()
    raised_l = np.asarray(core.raised, dtype=bool).ravel()[cells].tolist()
    flag_l = np.asarray(core.flag, dtype=bool).ravel()[cells].tolist()
    area_l = area_flat[cells].tolist()
    count_l = np.asarray(core.count, dtype=np.int64).ravel()[cells].tolist()
    starts = np.flatnonzero((feeds == 0) | (feeds >= 2)).tolist()
    link_of = {s: n for n, s in enumerate(starts)}

    traced = []
    for s in starts:
        own = [s]
        cur = s
        joins = -1
        end = None
        while True:
            d = down_l[cur]
            if d >= 0:
                if feeds_l[d] >= 2:
                    outlet, joins, end = "confluence", link_of[d], (row_l[d], col_l[d])
                    break
                own.append(d)
                cur = d
            elif code_l[cur] == FLOWS_OUT:
                outlet = "edge" if edge_l[cur] else "void"
                break
            elif code_l[cur] == 0:
                outlet = "sink"          # a flat left without a direction: never expected
                break
            else:
                outlet, end = "sea", next_l[cur]
                break
        traced.append((own, outlet, joins, end))

    # Strahler orders, upstream first: a line's first cell gathers more
    # cells than any cell upstream of it, so ordering by that count, then
    # by the cell (``starts`` is in grid order), puts every line after the
    # lines that join it.
    joining: dict[int, list[int]] = {}
    for n, (_, _, joins, _) in enumerate(traced):
        if joins >= 0:
            joining.setdefault(joins, []).append(n)
    order = [0] * len(traced)
    for n in sorted(range(len(traced)), key=lambda n: (count_l[starts[n]], starts[n])):
        incoming = [order[m] for m in joining.get(n, ())]
        if not incoming:
            order[n] = 1
        else:
            top = max(incoming)
            order[n] = top + 1 if incoming.count(top) >= 2 else top

    links = []
    parts = []
    for n, (own, outlet, joins, end) in enumerate(traced):
        places = [(row_l[x], col_l[x]) for x in own]
        if end is not None:
            places.append(end)
        keys = [(code_l[x], flat_l[x]) for x in own]
        turns = [m for m in range(1, len(own)) if keys[m] != keys[m - 1]]
        last = own[-1]
        whole = _vertex_positions(turns, 0, len(places))
        links.append(DrainageLink(
            id=n, start=int(cells[own[0]]), vertices=tuple(places[m] for m in whole), cells=len(own),
            outlet=outlet, downstream=joins, strahler=order[n], area_units=area_l[last],
            length_m=_summed([dist_l[x] for x in own[:len(places) - 1]]),
            edge_contaminated=flag_l[last], filled_cells=sum(raised_l[x] for x in own),
            flat_routed_cells=sum(flat_l[x] for x in own),
        ))

        # The runs of positions inside the square shown.
        inside = [r0 <= r < r1 and c0 <= c < c1 for r, c in places]
        piece = 0
        m = 0
        while m < len(places):
            if not inside[m]:
                m += 1
                continue
            a = m
            while m < len(places) and inside[m]:
                m += 1
            if m - a < 2:
                continue
            mine = own[a:min(m, len(own))]
            kept = _vertex_positions(turns, a, m)
            parts.append(DrainagePart(
                id=n, part=piece, vertices=tuple(places[v] for v in kept),
                stretch_flat=tuple(flat_l[own[v]] for v in kept[:-1]),
                outlet=outlet if m == len(places) else "beyond_view", strahler=order[n], downstream=joins,
                area_units=area_l[mine[-1]], length_m=_summed([dist_l[x] for x in own[a:m - 1]]),
                edge_contaminated=flag_l[mine[-1]], filled_cells=sum(raised_l[x] for x in mine),
                flat_routed_cells=sum(flat_l[x] for x in mine),
            ))
            piece += 1
    return tuple(links), tuple(parts)


def _json_text(text: str) -> str:
    """A string as JSON writes it with every character outside ASCII
    escaped, as the browser's ``jsonAscii`` writes it: a file name in any
    script then gives the same bytes in both engines."""
    return json.dumps(str(text), ensure_ascii=True)


def drainage_geojson(core: TerrainCore, parts: Sequence[DrainagePart], meta: Mapping) -> str:
    """The drainage lines shown, as GeoJSON text written by hand, without
    whitespace, in a fixed key order, so that both engines write the same
    bytes.

    ``meta`` holds ``label`` (what the files are), ``credit`` (what their
    licence asks a product to carry, "" where none), ``notice`` (the
    Copernicus liability sentence, or None), ``surface`` (what the heights
    are heights of), ``area`` (the drainage threshold in km²), ``radius``
    and ``margin`` (km) and ``centre``, the window's centre with its
    ``lon``, ``lat`` and ``label``. The description says what the lines
    are and are not, in the catalogue's words; the notice is written only
    for a set holding a Copernicus file, as its licence asks. Coordinates
    have six decimals (about 0.1 m) and areas six in km², lengths one in
    metres, all rounded as Python rounds; parts are written in the order
    given, which :func:`drainage_links` makes ``(id, part)``.
    """
    centre = meta["centre"]
    description = phrase("terrain.geojson_description", label=meta["label"], area=meta["area"],
                         radius=meta["radius"], where=centre.label, margin=meta["margin"],
                         surface=meta["surface"])
    out = ['{"type":"FeatureCollection","description":', _json_text(description),
           ',"attribution":', _json_text(meta["credit"])]
    if meta.get("notice"):
        out += [',"notice":', _json_text(meta["notice"])]
    out += [f',"drainage_area_km2":{float(meta["area"]):g}', f',"radius_km":{float(meta["radius"]):g}',
            f',"margin_km":{float(meta["margin"]):g}',
            f',"centre":[{float(centre.lon):.6f},{float(centre.lat):.6f}],"features":[']
    lons = np.asarray(core.lons, dtype=np.float64)
    lats = np.asarray(core.lats, dtype=np.float64)
    for n, part in enumerate(parts):
        line = ",".join(f"[{float(lons[c]):.6f},{float(lats[r]):.6f}]" for r, c in part.vertices)
        out.append(
            ("," if n else "")
            + f'{{"type":"Feature","properties":{{"id":{part.id},"part":{part.part},'
            + f'"strahler":{part.strahler},"outlet":{_json_text(part.outlet)},'
            + f'"area_km2":{part.area_units / 1e8:.6f},"length_m":{part.length_m:.1f},'
            + f'"edge_contaminated":{"true" if part.edge_contaminated else "false"},'
            + f'"filled_cells":{part.filled_cells},"flat_routed_cells":{part.flat_routed_cells},'
            + f'"downstream":{part.downstream}}},"geometry":{{"type":"LineString","coordinates":[{line}]}}}}'
        )
    out.append("]}")
    return "".join(out)


def _square(shown: Sequence[int] | None, rows: int, cols: int) -> tuple[int, int, int, int]:
    """The square shown as rows ``r0:r1`` and columns ``c0:c1`` of the grid,
    the whole grid when None, refused unless it lies inside the grid."""
    if shown is None:
        return 0, rows, 0, cols
    r0, r1, c0, c1 = (int(v) for v in shown)
    if not (0 <= r0 < r1 <= rows and 0 <= c0 < c1 <= cols):
        raise ValueError(f"the square shown, rows {r0}:{r1} and columns {c0}:{c1}, "
                         f"is not inside the {rows} by {cols} grid")
    return r0, r1, c0, c1


def _share(count: int, total: int) -> float:
    """``count`` as a percentage of ``total``, written as the browser
    writes it; 0 of nothing is 0."""
    return (100.0 * count) / total if total else 0.0


def _window_counts(z: np.ndarray, assumed: np.ndarray, cls: np.ndarray, zero_fill: np.ndarray,
                   view: tuple[slice, slice]) -> dict:
    """What each cell of the square shown is. Together they count every
    cell once: land, sea with a height, assumed sea, a zero-filled gap, or
    no height in the window at all (``uncovered``), which is either no
    value (``voids``) or an infinite one (``implausible``). The analysis
    cannot tell a reader's no-data cell from one it voided as implausible
    or one no file supplies, since all three arrive as NaN; the read report
    counts those apart over the whole window."""
    kind = cls[view]
    assumed = assumed[view]
    z = z[view]
    sea = kind == SEA
    missing = ~np.isfinite(z) & ~assumed
    infinite = np.isinf(z) & ~assumed
    uncovered = int(np.count_nonzero(missing))
    implausible = int(np.count_nonzero(infinite))
    return {
        "cells": int(kind.size),
        "land": int(np.count_nonzero(kind == LAND)),
        "sea": int(np.count_nonzero(sea & ~assumed)),
        "assumed_sea": int(np.count_nonzero(sea & assumed)),
        "voids": uncovered - implausible,
        "uncovered": uncovered,
        "implausible": implausible,
        "zero_fill": int(np.count_nonzero(zero_fill[view])),
    }


def analyse_terrain(grid: ElevationGrid, cfg: TerrainConfig | None = None, *, assumed_sea=None,
                    shown: Sequence[int] | None = None, progress: Callable[[float, str], None] | None = None,
                    precision: str = "float32") -> TerrainAnalysis:
    """Analyse a window of an elevation model: where water would run, the
    drainage lines, the shading, the wetness index and the curvature.

    ``assumed_sea`` marks a missing tile taken as open sea, which has no
    height (an :class:`.elevation.ElevationRead` gives it); ``shown`` is
    the square shown, as rows ``r0:r1`` and columns ``c0:c1`` of the grid
    (the whole grid when None). The window beyond it is the margin: it is
    analysed so that the edge of the analysis does not bend the lines, but
    the lines are cut and the summary counted where the map ends. The
    source's sea rule comes from ``grid.sea_clean``. ``progress(fraction,
    label)``, when given, hears each stage start, in the catalogue's words.

    Every count, threshold, drainage line and display limit is taken in
    float64 or from integers. With ``precision="float32"`` the layers that
    are only drawn - the slope, the hillshades, the wetness index, the
    curvatures and the fill depth - are then kept in float32, which halves
    the memory those layers take at the cap; a threshold taken after
    narrowing would move (57 of a million cells changed their fill verdict
    in a test of float64 heights). ``p``, ``q``, ``twi_arg``, the filled
    surface, the core and the lines keep full precision whatever is asked.
    """
    cfg = TerrainConfig() if cfg is None else cfg
    if precision not in ("float32", "float64"):
        raise ValueError(f"precision must be 'float32' or 'float64', not {precision!r}")
    narrow = precision == "float32"

    def keep(layer: np.ndarray) -> np.ndarray:
        return layer.astype(np.float32) if narrow else layer

    # Each stage is announced with the share of the whole that has gone
    # before it, as measured at the default window (the fill takes about a
    # third of the time).
    def stage(fraction: float, label: str) -> None:
        if progress is not None:
            progress(fraction, label)

    z = np.add(np.asarray(grid.z, dtype=np.float64), 0.0)          # -0 becomes +0
    rows, cols = z.shape
    square = _square(shown, rows, cols)
    view = (slice(square[0], square[1]), slice(square[2], square[3]))
    if assumed_sea is None:
        assumed = np.zeros((rows, cols), dtype=bool)
    else:
        assumed = _grid("assumed_sea", assumed_sea, (rows, cols)).astype(bool)
    metric = row_metric(grid.lons, grid.lats)
    threshold = _threshold_units(cfg.drainage_area_km2)

    stage(0.0, phrase("terrain.stage_classes"))
    cls, seed, zero_fill, zt = classify_cells(z, cfg.sea_level_m, assumed, cfg.sea_straight_edge_cells)
    summary = _window_counts(z, assumed, cls, zero_fill, view)
    del z, zero_fill

    stage(0.15, phrase("terrain.stage_fill"))
    filled = fill_depressions(zt, cls, seed)
    stage(0.45, phrase("terrain.stage_flow"))
    code_d8 = flow_directions(zt, filled, cls, seed, metric, cfg.sea_level_m)
    del seed
    stage(0.5, phrase("terrain.stage_flats"))
    code, unresolved = resolve_flats(filled, cls, code_d8)
    land = cls == LAND
    fill_depth = np.where(land, filled - zt, np.nan)
    raised = land & (fill_depth >= cfg.fill_note_m)
    flat_routed = land & ((code_d8 == 0) | (fill_depth > 0.0))
    del code_d8
    depth_shown = fill_depth[view][land[view]]
    max_fill = float(depth_shown.max()) if depth_shown.size else 0.0
    del depth_shown
    fill_depth = keep(fill_depth)

    stage(0.6, phrase("terrain.stage_accumulate"))
    count, area_units, flag = accumulate_flow(code, cls, metric, grid.sea_clean)
    core = TerrainCore(
        rows=rows, cols=cols, shown=square, lons=np.asarray(grid.lons, dtype=np.float64),
        lats=np.asarray(grid.lats, dtype=np.float64), dx=metric.dx, dy=metric.dy, dg=metric.dg,
        cls=cls, code=code, flag=flag, raised=raised, flat_routed=flat_routed, count=count,
        area_units=area_units,
    )

    stage(0.7, phrase("terrain.stage_drainage"))
    links, parts = drainage_links(core, cfg.drainage_area_km2)
    stream = land & (area_units >= threshold)

    stage(0.75, phrase("terrain.stage_shading"))
    p, q, tanb = horn_gradients(zt, metric)
    altitude, z_factor = cfg.hillshade_altitude_deg, cfg.hillshade_z_factor
    hillshades = tuple(keep(hillshade_layer(p, q, azimuth, altitude, z_factor))
                       for azimuth in cfg.hillshade_panel_azimuths_deg)
    hillshade_multi = keep(multidirectional_hillshade(p, q, cfg.hillshade_azimuths_deg, altitude, z_factor))

    label_curvature = phrase("terrain.stage_curvature")
    stage(0.85, label_curvature)
    twi_arg, twi, floored = wetness_index(area_units, cls, tanb, metric, cfg.flat_tan_slope)
    twi = keep(twi)
    tanb = keep(tanb)
    profile, tangential, k_cells = curvatures(zt, cls, metric, cfg.curvature_spacing_m, cfg.flat_tan_slope)
    bend = np.abs(np.concatenate([profile[view].ravel(), tangential[view].ravel()]))
    curvature_limit = display_range(bend, 0.98, 0.98)[0]
    del bend
    profile = keep(profile)
    tangential = keep(tangential)

    # The relief counts every finite height of the square shown, sea with a
    # height included; the wetness range is chosen on the exact argument and
    # only the two chosen values pass through a logarithm.
    heights = zt[view]
    heights = heights[np.isfinite(heights)]
    relief = float(heights.max() - heights.min()) if heights.size else math.nan
    del heights, zt
    low, high = display_range(twi_arg[view], 0.02, 0.98)
    with np.errstate(invalid="ignore"):
        twi_range = (float(np.log(low)), float(np.log(high)))
    floored_shown = int(np.count_nonzero(floored[view]))
    del floored
    stream_shown = stream[view]
    n_stream = int(np.count_nonzero(stream_shown))
    n_flat = int(np.count_nonzero(stream_shown & flat_routed[view]))
    n_flagged = int(np.count_nonzero(stream_shown & flag[view]))
    n_raised = int(np.count_nonzero(raised[view]))
    summary.update(
        raised=n_raised, flat_routed_stream=n_flat, stream=n_stream, contaminated_stream=n_flagged,
        unresolved=int(unresolved), floored=floored_shown,
        raised_pct=_share(n_raised, summary["land"]), flat_routed_lines_pct=_share(n_flat, n_stream),
        contaminated_pct=_share(n_flagged, n_stream),
        sea_pct=_share(summary["sea"] + summary["assumed_sea"], summary["cells"]),
        zero_fill_pct=_share(summary["zero_fill"], summary["cells"]),
        max_fill_m=max_fill, k_cells=int(k_cells), threshold_units=threshold, relief=relief,
        contour_interval=contour_interval(relief), twi_range=twi_range, curvature_limit=curvature_limit,
    )
    stage(1.0, label_curvature)
    return TerrainAnalysis(
        grid=grid, metric=metric, core=core, filled=filled, fill_depth=fill_depth, unresolved=int(unresolved),
        stream=stream, links=links, parts=parts, p=p, q=q, tanb=tanb, hillshades=hillshades,
        hillshade_multi=hillshade_multi, twi_arg=twi_arg, twi=twi, profile=profile, tangential=tangential,
        k_cells=int(k_cells), floored=floored_shown, zero_fill=summary["zero_fill"], summary=summary,
        settings=cfg,
    )


def _surface_note(source_id: str) -> str:
    """What the heights are heights of, by the product a grid was read as,
    for a grid that came without a read report (an ``.asc`` or ``.xyz``
    file)."""
    if source_id == "copernicus_glo30":
        return phrase("terrain.surface_copernicus")
    if source_id in ("srtm", "hgt"):
        return phrase("terrain.surface_srtm")
    return phrase("terrain.surface_unknown")


def terrain_captions(analysis: TerrainAnalysis, read: ElevationRead | None, where: str) -> dict[str, str]:
    """Every sentence the terrain figures and the drainage lines carry, in
    the catalogue's words, so that both apps print the same.

    ``read`` is the read the window came from, or None for a grid read
    whole (an ``.asc`` or ``.xyz`` file): it says what the heights are
    heights of, and the radius and margin of the window. ``where`` names
    the place, as the read report does.

    The keys are ``title_relief``, ``title_wetness``, ``title_curvature``
    and ``title_directions``; ``panel_0`` onwards, the title of each panel
    lit from one direction, in the panel azimuths' order; ``relief``,
    ``wetness``, ``curvature`` and ``directions``, each figure's captions
    as one paragraph in the order they are printed under it, which says
    what the figure can be trusted for (the sea, a zero-filled gap and an
    unresolved flat are mentioned only where the square shows one);
    ``figure_caveat``, the line drawn inside every figure under its credit;
    ``geojson_description``; and the analysis's stage labels, under their
    own ids (``stage_classes`` to ``stage_curvature``).
    """
    cfg = analysis.settings
    summary = analysis.summary
    surface = read.surface if read is not None and read.surface else _surface_note(analysis.grid.source_id)
    radius, margin = cfg.analysis_radius_km, cfg.analysis_buffer_km
    if read is not None and read.plan is not None:
        radius, margin = read.plan.radius_km, read.plan.margin_km
    level = cfg.sea_level_m
    candidates = phrase("terrain.caption_candidates")

    relief = [
        phrase("terrain.caption_relief", interval=summary["contour_interval"], area=cfg.drainage_area_km2),
        phrase("terrain.caption_fill", lines_pct=summary["flat_routed_lines_pct"], pct=summary["raised_pct"],
               depth=cfg.fill_note_m),
        phrase("terrain.caption_edge", margin=margin),
    ]
    if summary["sea_pct"] > 0:
        relief.append(phrase("terrain.caption_sea", pct=summary["sea_pct"], level=level))
    if not analysis.grid.sea_clean and summary["sea"] + summary["assumed_sea"] > 0:
        relief.append(phrase("terrain.caption_sea_unstated", level=level))
    if summary["zero_fill"] > 0:
        relief.append(phrase("terrain.caption_zero_fill", pct=summary["zero_fill_pct"], level=level))
    if summary["unresolved"] > 0:
        relief.append(phrase("terrain.caption_unresolved", n=summary["unresolved"]))
    relief.append(candidates)
    # the spacing the curvature was taken over, in metres of the middle row
    mid = analysis.core.rows // 2
    spacing = analysis.k_cells * ((float(analysis.core.dx[mid]) + float(analysis.core.dy[mid])) / 2.0)
    azimuths = cfg.hillshade_panel_azimuths_deg

    out = {
        "title_relief": phrase("terrain.title_relief", where=where),
        "title_wetness": phrase("terrain.title_wetness", where=where),
        "title_curvature": phrase("terrain.title_curvature", where=where),
        "title_directions": phrase("terrain.title_directions", where=where),
    }
    for n, azimuth in enumerate(azimuths):
        out[f"panel_{n}"] = phrase("terrain.panel_azimuth", az=azimuth)
    out.update(
        relief=" ".join(relief),
        wetness=" ".join([phrase("terrain.caption_twi", floor=cfg.flat_tan_slope, n=summary["floored"]),
                          candidates, surface]),
        curvature=" ".join([phrase("terrain.caption_curvature", spacing=spacing, floor=cfg.flat_tan_slope),
                            candidates, surface]),
        directions=phrase("terrain.caption_directions",
                          azimuths=and_join([f"{float(azimuth):g}°" for azimuth in azimuths]),
                          altitude=cfg.hillshade_altitude_deg),
        figure_caveat=phrase("terrain.figure_caveat", surface=surface),
        geojson_description=phrase("terrain.geojson_description", label=analysis.grid.source,
                                   area=cfg.drainage_area_km2, radius=radius, where=where, margin=margin,
                                   surface=surface),
        stage_classes=phrase("terrain.stage_classes"),
        stage_fill=phrase("terrain.stage_fill"),
        stage_flow=phrase("terrain.stage_flow"),
        stage_flats=phrase("terrain.stage_flats"),
        stage_accumulate=phrase("terrain.stage_accumulate"),
        stage_drainage=phrase("terrain.stage_drainage"),
        stage_shading=phrase("terrain.stage_shading"),
        stage_curvature=phrase("terrain.stage_curvature"),
    )
    return out


# --- surface (spec 3.11-3.15)
#
# Shading, slope, wetness and curvature, written as the browser's engine
# writes them: additions, multiplications, divisions and square roots in
# the order given, element by element, and the sine and cosine of an angle
# only through sin_cos_deg, so that the two engines give the same bits.
# numpy applies each operator on its own and never fuses a multiply into
# an add, so slice arithmetic keeps that order; a sum or a mean over an
# axis, np.hypot or numpy's sine would not, and none is used. The wetness
# index's logarithm is the one library call, and the only value the parity
# suite compares at a tolerance.
#
# Each kernel works through the grid a band of rows at a time. A formula
# written on whole grids makes a temporary grid for every operation, and
# the curvature's would hold fifteen grids at once, 240 MB at the cap on
# cells; a band holds a few megabytes. A cell's arithmetic is the same
# whichever band it falls in.

#: About this many cells are worked on at once.
_BAND_CELLS = 1 << 18


def _bands(start: int, stop: int, width: int) -> Iterator[tuple[int, int]]:
    """Half-open runs of rows (or of elements) from ``start`` to ``stop``,
    each about :data:`_BAND_CELLS` cells of a grid ``width`` wide."""
    step = max(1, _BAND_CELLS // max(width, 1))
    for lo in range(start, stop, step):
        yield lo, min(lo + step, stop)


def _surface_grid(name: str, a, dtype: type | None = np.float64) -> np.ndarray:
    """``a`` as a two-dimensional array of ``dtype`` (its own when None),
    refused otherwise."""
    a = np.asarray(a, dtype=dtype)
    if a.ndim != 2:
        raise ValueError(f"{name} must be a two-dimensional grid, not an array of shape {a.shape}")
    return a


def _rows_of(metric: RowMetric, rows: int) -> tuple[np.ndarray, np.ndarray]:
    """The metric's east-west and north-south cell sizes, one per row.
    Both engines refuse a metric of any other length, which would be read
    past its end (NaN in the browser) or belong to another grid."""
    dx = np.asarray(metric.dx, dtype=np.float64)
    dy = np.asarray(metric.dy, dtype=np.float64)
    if dx.shape != (rows,) or dy.shape != (rows,):
        raise ValueError(f"the metric must have one cell size per row ({rows})")
    return dx, dy


class _Band:
    """Rows ``r0`` to ``r1`` and columns ``c0`` to ``c1`` (half-open) of a
    grid, and the views of a grid offset from them."""

    def __init__(self, r0: int, r1: int, c0: int, c1: int) -> None:
        self.r0, self.r1, self.c0, self.c1 = r0, r1, c0, c1

    def at(self, a: np.ndarray, dr: int = 0, dc: int = 0) -> np.ndarray:
        """``a[r + dr, c + dc]`` for every cell ``(r, c)`` of the band, as a
        view (north is ``dr = 1``)."""
        return a[self.r0 + dr:self.r1 + dr, self.c0 + dc:self.c1 + dc]

    def all_finite(self, finite: np.ndarray, k: int) -> np.ndarray:
        """Whether each cell of the band and the eight cells ``k`` apart
        around it are all ``finite``."""
        ok = self.at(finite).copy()
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr or dc:
                    ok &= self.at(finite, dr * k, dc * k)
        return ok


def horn_gradients(zt, metric: RowMetric) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The slope of the ground at every cell, by Horn's (1981) 3x3 rule on
    the raw heights.

    Returns ``(p, q, tanb)``: ``p`` the rise per metre eastwards, ``q`` the
    rise per metre northwards (row + 1), and ``tanb`` the tangent of the
    slope, ``sqrt(p*p + q*q)``. They are unscaled; a z-factor is applied by
    the shading, not here, so the wetness index and the slope always see
    the ground as it is.

    A value is given only where the cell and all eight neighbours are in
    the grid and have a finite height; anywhere else it is NaN, which is
    GDAL's rule. Filling a void or the edge with a stand-in height draws a
    cliff where the model simply says nothing. Sea with a height counts as
    ground; a void and assumed sea have none (``zt`` is NaN there).

    Each row's own cell size is used (``metric``, from
    :func:`.elevation.row_metric`), because a cell 1 arc-second wide narrows
    by 0.26% across one tile.
    """
    z = _surface_grid("zt", zt)
    rows, cols = z.shape
    dx, dy = _rows_of(metric, rows)
    p = np.full((rows, cols), np.nan)
    q = np.full((rows, cols), np.nan)
    tanb = np.full((rows, cols), np.nan)
    if rows < 3 or cols < 3:
        return p, q, tanb
    finite = np.isfinite(z)
    for r0, r1 in _bands(1, rows - 1, cols):
        b = _Band(r0, r1, 1, cols - 1)
        z_n, z_s, z_e, z_w = b.at(z, 1, 0), b.at(z, -1, 0), b.at(z, 0, 1), b.at(z, 0, -1)
        z_ne, z_nw, z_se, z_sw = b.at(z, 1, 1), b.at(z, 1, -1), b.at(z, -1, 1), b.at(z, -1, -1)
        with np.errstate(invalid="ignore"):
            bp = (((z_ne + 2.0 * z_e) + z_se) - ((z_nw + 2.0 * z_w) + z_sw)) / (8.0 * dx[r0:r1, None])
            bq = (((z_nw + 2.0 * z_n) + z_ne) - ((z_sw + 2.0 * z_s) + z_se)) / (8.0 * dy[r0:r1, None])
        missing = ~b.all_finite(finite, 1)
        bp[missing] = np.nan
        bq[missing] = np.nan
        b.at(p)[...] = bp
        b.at(q)[...] = bq
        b.at(tanb)[...] = np.sqrt(bp * bp + bq * bq)
    return p, q, tanb


def _flat_pair(p, q) -> tuple[np.ndarray, np.ndarray, tuple[int, ...]]:
    """``p`` and ``q`` as float64 runs of one length, and their shape."""
    p = np.asarray(p, dtype=np.float64)
    q = np.asarray(q, dtype=np.float64)
    if p.shape != q.shape:
        raise ValueError(f"p and q must have one shape, not {p.shape} and {q.shape}")
    return p.reshape(-1), q.reshape(-1), p.shape


def hillshade_layer(p, q, azimuth_deg: float, altitude_deg: float, z_factor: float | None = 1.0) -> np.ndarray:
    """The ground lit by a sun at ``azimuth_deg`` (clockwise from north)
    and ``altitude_deg`` above the horizon: the cosine of the angle between
    the sun and the ground's normal, 0 in shadow to 1 facing the sun.

    This is GDAL's hillshade with Horn's gradients (``gdaldem hillshade``),
    written from ``p`` and ``q`` of :func:`horn_gradients`, scaled by
    ``z_factor`` (1 when None). A slope turned away from the sun is 0, not
    negative, and NaN stays NaN where the gradient is not defined, rather
    than reading as flat ground in shadow.
    """
    flat_p, flat_q, shape = _flat_pair(p, q)
    # None means 1, as null or a value left out does in the browser's
    # hillshades (where null once multiplied as 0)
    zf = 1.0 if z_factor is None else float(z_factor)
    s_az, c_az = sin_cos_deg(azimuth_deg)
    s_alt, c_alt = sin_cos_deg(altitude_deg)
    shade = np.empty(flat_p.size)
    for i0, i1 in _bands(0, flat_p.size, 1):
        big_p = flat_p[i0:i1] * zf
        big_q = flat_q[i0:i1] * zf
        with np.errstate(invalid="ignore"):
            g = big_p * s_az + big_q * c_az
            v = (s_alt - c_alt * g) / np.sqrt((1.0 + big_p * big_p) + big_q * big_q)
        # a literal 0, so that no -0 appears, and NaN by test rather than by
        # whatever a comparison with NaN happens to give
        v = np.where(v > 0.0, v, 0.0)
        v[np.isnan(big_p)] = np.nan
        shade[i0:i1] = v
    return shade.reshape(shape)


def multidirectional_hillshade(p, q, azimuths: Sequence[float], altitude_deg: float,
                               z_factor: float | None = 1.0) -> np.ndarray:
    """The ground lit from several azimuths at once, each sun weighted by
    how squarely it lights the local slope: ``gdaldem hillshade
    -multidirectional`` exactly when ``azimuths`` is 225, 270, 315 and 360.

    GDAL weights each azimuth by ``(p*sin az + q*cos az)**2``, the square
    of the slope's component towards that sun (its fixed weights for the
    four azimuths are these terms written out), so a slope is shaded mostly
    by the suns that light it across. That is GDAL's local-aspect rule, not
    Mark (1992), who weights by an aspect smoothed over a kilometre. Flat
    ground, where every weight is 0, is lit at the sine of the altitude.
    The azimuths are taken in the order given; ``z_factor`` is 1 when None.
    """
    flat_p, flat_q, shape = _flat_pair(p, q)
    zf = 1.0 if z_factor is None else float(z_factor)   # None means 1, as in hillshade_layer
    s_alt, c_alt = sin_cos_deg(altitude_deg)
    suns = [sin_cos_deg(azimuth) for azimuth in azimuths]
    shade = np.empty(flat_p.size)
    for i0, i1 in _bands(0, flat_p.size, 1):
        big_p = flat_p[i0:i1] * zf
        big_q = flat_q[i0:i1] * zf
        num = np.zeros(i1 - i0)
        den = np.zeros(i1 - i0)
        with np.errstate(invalid="ignore", divide="ignore"):
            for s_az, c_az in suns:
                g = big_p * s_az + big_q * c_az
                lit = s_alt - c_alt * g
                lit = np.where(lit > 0.0, lit, 0.0)
                w = g * g
                num = num + w * lit
                den = den + w
            v = (num / den) / np.sqrt((1.0 + big_p * big_p) + big_q * big_q)
        v = np.where(den > 0.0, v, s_alt)
        v[np.isnan(big_p)] = np.nan
        shade[i0:i1] = v
    return shade.reshape(shape)


def wetness_index(area_units, cls, tanb, metric: RowMetric, flat_tan_slope: float
                  ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The topographic wetness index, ``ln(a / tan b)``, of every land cell.

    ``a`` is the specific catchment area in metres: the upslope area
    (``area_units``, in whole 0.01 square metres, from the D8 routing)
    divided by the mean side of the cell, as WhiteboxTools takes the
    contour width. ``tan b`` is the local slope on the unfilled surface
    (:func:`horn_gradients`; Kopecky et al. 2021). A slope gentler than
    ``flat_tan_slope`` is taken as that floor rather than left undefined,
    because NaN would blank the floors of the inland-valley swamps, which
    are the wettest ground there is.

    Returns ``(arg, twi, floored)``: the exact ``a / tan b``, kept so that
    the display range can be chosen on it rather than on its logarithm (a
    logarithm from another engine's library may tie or swap two values the
    argument keeps apart); the index; and the mask of the cells whose
    slope was floored. Sea, voids and cells with no slope are NaN and not
    floored.
    """
    tanb = _surface_grid("tanb", tanb)
    rows, cols = tanb.shape
    cls = _surface_grid("cls", cls, dtype=np.uint8)
    area = _surface_grid("area_units", area_units, dtype=None)
    if cls.shape != tanb.shape or area.shape != tanb.shape:
        raise ValueError("area_units, cls and tanb must be grids of one shape")
    dx, dy = _rows_of(metric, rows)
    floor = float(flat_tan_slope)
    # Both engines refuse a floor that is not a finite positive slope (NaN
    # included), here and in the curvatures: 0 would divide by 0 on level
    # ground and an infinite one would set every argument to 0.
    if not 0.0 < floor < math.inf:
        raise ValueError(f"flat_tan_slope must be a finite positive slope, not {flat_tan_slope!r}")
    width = (dx + dy) / 2.0
    arg = np.full((rows, cols), np.nan)
    twi = np.full((rows, cols), np.nan)
    floored = np.zeros((rows, cols), dtype=bool)
    for r0, r1 in _bands(0, rows, cols):
        band_tanb = tanb[r0:r1]
        with np.errstate(invalid="ignore", divide="ignore"):
            # whole units of area are exact in float64 below 2**53, as they
            # are in the browser's Float64Array
            a = (area[r0:r1].astype(np.float64) / 100.0) / width[r0:r1, None]
            tb = np.where(band_tanb >= floor, band_tanb, floor)
            band_arg = a / tb
        defined = (cls[r0:r1] == LAND) & ~np.isnan(band_tanb)
        band_arg[~defined] = np.nan
        arg[r0:r1] = band_arg
        with np.errstate(divide="ignore"):    # an argument of 0 (no area, or an infinite slope) is -inf
            twi[r0:r1][defined] = np.log(band_arg[defined])
        floored[r0:r1] = defined & ~(band_tanb >= floor)
    return arg, twi, floored


def _curvature_cells(metric: RowMetric, spacing_m: float) -> int:
    """How many cells apart the curvature samples are: ``spacing_m`` in
    cells of the middle row, rounded half up, at least 1 (3 at 1
    arc-second and 1 at 3 for the default 90 m)."""
    dx = np.asarray(metric.dx, dtype=np.float64)
    dy = np.asarray(metric.dy, dtype=np.float64)
    # Both engines refuse, rather than fall back to k = 1: a spacing that is
    # not a finite positive number of metres, a grid with no middle row to
    # measure it on, and a spacing so many cells long that k is not finite.
    spacing = float(spacing_m)
    if not (math.isfinite(spacing) and spacing > 0.0):
        raise ValueError(f"the curvature spacing must be a positive number of metres, not {spacing_m!r}")
    if dx.size == 0:
        raise ValueError("a grid with no rows has no middle row to measure the curvature spacing on")
    mid = dx.size // 2
    cells = spacing / ((float(dx[mid]) + float(dy[mid])) / 2.0) + 0.5
    if not math.isfinite(cells):
        raise ValueError(f"a curvature spacing of {spacing_m!r} m is no finite number of cells")
    return max(1, math.floor(cells))


def curvatures(zt, cls, metric: RowMetric, spacing_m: float, flat_tan_slope: float
               ) -> tuple[np.ndarray, np.ndarray, int]:
    """Profile and tangential curvature of the land, by Evans and Young's
    quadratic fitted to nine heights ``spacing_m`` apart.

    Returns ``(profile, tangential, k_cells)``, in 1/m, with the signs of
    Florinsky and Minar et al. (2020): profile curvature is positive where
    the ground is convex down the slope, so flow speeds up, and negative
    where it is concave; tangential curvature is negative where flow
    converges (hollows) and positive where it diverges (spurs). A dome is
    positive in both. ESRI's legacy profile sign is the other way.

    The samples are ``k_cells`` cells apart (``spacing_m`` in cells of the
    middle row, rounded, at least 1) rather than 1, so that the noise of a
    30 m surface model, about 1.5e-3 per metre over 3x3 cells, falls to
    about 1.7e-4 against signals near 6e-4. A value is given only on land,
    where all nine samples are in the grid and have a height, and where the
    slope is at least ``flat_tan_slope``: on flatter ground the direction
    of the slope, and so both curvatures, is undefined.
    """
    z = _surface_grid("zt", zt)
    rows, cols = z.shape
    cls = _surface_grid("cls", cls, dtype=np.uint8)
    if cls.shape != z.shape:
        raise ValueError("cls and zt must be grids of one shape")
    dx, dy = _rows_of(metric, rows)
    k = _curvature_cells(metric, spacing_m)
    floor = float(flat_tan_slope)
    if not 0.0 < floor < math.inf:            # the wetness index's rule, in both engines
        raise ValueError(f"flat_tan_slope must be a finite positive slope, not {flat_tan_slope!r}")
    profile = np.full((rows, cols), np.nan)
    tangential = np.full((rows, cols), np.nan)
    if rows <= 2 * k or cols <= 2 * k:
        return profile, tangential, k
    finite = np.isfinite(z)
    for r0, r1 in _bands(k, rows - k, cols):
        b = _Band(r0, r1, k, cols - k)
        # Evans and Young's z1..z9: NW, N, NE, W, centre, E, SW, S, SE
        z1, z2, z3 = b.at(z, k, -k), b.at(z, k, 0), b.at(z, k, k)
        z4, z5, z6 = b.at(z, 0, -k), b.at(z), b.at(z, 0, k)
        z7, z8, z9 = b.at(z, -k, -k), b.at(z, -k, 0), b.at(z, -k, k)
        big_x = k * dx[r0:r1, None]
        big_y = k * dy[r0:r1, None]
        with np.errstate(invalid="ignore", divide="ignore"):
            p = (((((z3 + z6) + z9) - z1) - z4) - z7) / (6.0 * big_x)
            q = (((((z1 + z2) + z3) - z7) - z8) - z9) / (6.0 * big_y)
            r = ((((((z1 + z3) + z4) + z6) + z7) + z9) - 2.0 * ((z2 + z5) + z8)) / ((3.0 * big_x) * big_x)
            t = ((((((z1 + z2) + z3) + z7) + z8) + z9) - 2.0 * ((z4 + z5) + z6)) / ((3.0 * big_y) * big_y)
            s = (((z3 + z7) - z1) - z9) / ((4.0 * big_x) * big_y)
            g2 = p * p + q * q
            w = 1.0 + g2
            kv = -(((p * p) * r + ((2.0 * p) * q) * s) + (q * q) * t) / (g2 * (w * np.sqrt(w)))
            kh = -(((q * q) * r - ((2.0 * p) * q) * s) + (p * p) * t) / (g2 * np.sqrt(w))
        keep = (b.at(cls) == LAND) & b.all_finite(finite, k) & (g2 >= floor * floor)
        kv[~keep] = np.nan
        kh[~keep] = np.nan
        b.at(profile)[...] = kv
        b.at(tangential)[...] = kh
    return profile, tangential, k


def contour_interval(relief: float) -> float:
    """A round contour interval giving about a dozen lines over ``relief``
    metres: the largest of 1, 2, 5, 10, 20, 50, ... no more than a sixth of
    the relief, and at least 1 m.

    Sierra Leone's basement plains and the Freetown peninsula differ by
    two orders of magnitude in relief, so a fixed interval draws either two
    contours or four hundred. The candidates are whole numbers built by
    integer arithmetic rather than powers of ten from a logarithm, so the
    interval cannot depend on the last bit of a library's log10, and a
    relief that is not a finite positive number (no ground, or an infinite
    height that slipped through) gives 10 m rather than an overflow or a
    loop that never ends.
    """
    relief = float(relief)
    if not math.isfinite(relief) or relief <= 0.0:
        return 10.0
    limit = (relief / 12.0) * 2.0
    # The rule in both engines: the candidates are exact integers (int here,
    # BigInt in the browser), each compared exactly with the float limit,
    # and the answer is the float nearest the one chosen. A float walk
    # would round a candidate past 10**22 and could stop a step early.
    best = 1
    decade = 1
    while True:
        for step in (1, 2, 5):
            nice = step * decade
            if nice > limit:
                return float(best)
            best = nice
        decade *= 10


def display_range(values, lo: float, hi: float) -> tuple[float, float]:
    """The elements of the finite ``values``, sorted ascending, at the
    positions ``floor(lo*(n-1))`` and ``floor(hi*(n-1))``, so that both
    apps draw a layer between the same two numbers.

    These are elements of the data, not interpolated between them, so the
    choice is exact. The values are taken with any -0 made +0 first, so
    that which of two equal zeros comes first in the sort cannot change
    the answer's sign. With no finite value the range is ``(nan, nan)``.
    ``lo`` and ``hi`` are fractions, ``0 <= lo <= hi <= 1``.
    """
    lo = float(lo)
    hi = float(hi)
    # Both engines refuse fractions out of order or outside 0..1 (NaN
    # included) rather than hand back a range upside down.
    if not 0.0 <= lo <= hi <= 1.0:
        raise ValueError(f"a display range needs 0 <= lo <= hi <= 1, not lo={lo!r} and hi={hi!r}")
    v = np.asarray(values, dtype=np.float64).ravel()
    # A zero comes back as +0 in both engines: +0.0 is added here before the
    # choice and in the browser to the two elements chosen, which gives the
    # same bits whichever zero a sort put at the index.
    v = v[np.isfinite(v)] + 0.0
    n = int(v.size)
    if n == 0:
        return math.nan, math.nan
    i = math.floor(lo * (n - 1))
    j = math.floor(hi * (n - 1))
    chosen = np.partition(v, (i, j) if i != j else i)
    return float(chosen[i]), float(chosen[j])

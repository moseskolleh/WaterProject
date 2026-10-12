"""The terrain analysis: where water on an elevation model would run.

mapping/terrain_analysis.py sorts the cells into land, sea and void, fills
the hollows, routes every land cell to a neighbour (D8, then Barnes's
gradients across the flats) and adds up the area draining through each
cell. The browser's engine does the same with the same operations, and
the parity suite holds the two to the bit; these tests hold the Python one
to the rules, most of them against an independent way of getting the same
answer: a plain Priority-Flood and a morphological reconstruction for the
fill, Barnes's labelled flats for the flat directions, and a cell-by-cell
accumulation in another order for the areas.

The second half holds what is assembled from the routing: the drainage
lines (against the rules of the design written out one cell at a time),
their parts in the square shown, the GeoJSON, the summary, the float32
storage and the captions.

The grids are south-first, as the analysis holds them: row 0 is the south
edge and north is row + 1.
"""

from __future__ import annotations

import dataclasses
import hashlib
import heapq
import inspect
import json
import math
import re
import subprocess
import sys
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from groundwater.config import TerrainConfig
from groundwater.mapping.elevation import ElevationGrid, RowMetric, WindowCentre, read_elevation, row_metric
from groundwater.mapping.terrain_analysis import (
    LAND,
    SEA,
    VOID,
    DrainageLink,
    DrainagePart,
    TerrainCore,
    accumulate_flow,
    analyse_terrain,
    classify_cells,
    display_range,
    drainage_geojson,
    drainage_links,
    fill_depressions,
    flow_directions,
    horn_gradients,
    resolve_flats,
    terrain_captions,
)
from groundwater.text import phrase

# The neighbour order K (E, S, W, N, SE, SW, NW, NE) and its ESRI codes,
# written out again here so that a change to the module's is caught.
DR = (0, -1, 0, 1, -1, -1, 1, 1)
DC = (1, 0, -1, 0, 1, -1, -1, 1)
ESRI = (1, 4, 16, 64, 2, 8, 32, 128)
E, S, W, N, SE, SW, NW, NE = ESRI
nan = float("nan")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _metric(rows: int, cols: int, lat: float = 8.5, step: float = 1 / 3600) -> RowMetric:
    """The row metric of a 1 arc-second grid whose south row is at ``lat``."""
    lons = -12.0 + np.arange(cols) * step
    lats = lat + np.arange(rows) * step
    return row_metric(lons, lats)


def _route(z, sea_level=0.0, assumed_sea=None, sea_clean=True, straight_edge_cells=150):
    """The whole routing core, in the order the analysis runs it."""
    z = np.asarray(z, dtype=np.float64)
    cls, seed, zero_fill, zt = classify_cells(z, sea_level, assumed_sea, straight_edge_cells)
    filled = fill_depressions(zt, cls, seed)
    metric = _metric(*z.shape)
    code_d8 = flow_directions(zt, filled, cls, seed, metric, sea_level)
    code, unresolved = resolve_flats(filled, cls, code_d8)
    count, area, flag = accumulate_flow(code, cls, metric, sea_clean)
    return SimpleNamespace(cls=cls, seed=seed, zero_fill=zero_fill, zt=zt, filled=filled, metric=metric,
                           code_d8=code_d8, code=code, unresolved=unresolved, count=count, area=area,
                           flag=flag)


def _random_heights(seed: int, rows: int, cols: int, step: float = 0.1, relief: float = 3.0,
                    voids: float = 0.03) -> np.ndarray:
    """A rough surface tilted down to the south, below sea level along part
    of the south edge, in whole multiples of ``step`` so that equal heights
    and flats are common, with scattered voids."""
    rng = np.random.default_rng(seed)
    tilt = np.linspace(-0.6, relief, rows)[:, None]
    z = tilt + rng.uniform(0.0, relief, (rows, cols))
    z = np.round(z / step) * step
    z[rng.random((rows, cols)) < voids] = nan
    return z


def _neighbours(i: int, rows: int, cols: int):
    """The (k, index) of each neighbour of cell ``i`` inside the grid, in K order."""
    r, c = divmod(i, cols)
    for k in range(8):
        rr, cc = r + DR[k], c + DC[k]
        if 0 <= rr < rows and 0 <= cc < cols:
            yield k, rr * cols + cc


def _downstream(code: np.ndarray, cls: np.ndarray) -> list[int]:
    """The land cell each land cell drains to, or -1."""
    rows, cols = code.shape
    flat_code = code.ravel().tolist()
    flat_cls = cls.ravel().tolist()
    down = [-1] * (rows * cols)
    for i in range(rows * cols):
        if flat_cls[i] != LAND or flat_code[i] not in ESRI:
            continue
        k = ESRI.index(flat_code[i])
        r, c = divmod(i, cols)
        rr, cc = r + DR[k], c + DC[k]
        if 0 <= rr < rows and 0 <= cc < cols and flat_cls[rr * cols + cc] == LAND:
            down[i] = rr * cols + cc
    return down


def _digest(*arrays) -> str:
    """A digest of the arrays' bytes: unlike np.array_equal, it tells +0
    from -0."""
    h = hashlib.sha256()
    for a in arrays:
        a = np.ascontiguousarray(a)
        h.update(str(a.dtype).encode())
        h.update(a.tobytes())
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Oracles: other ways of getting the same answer, written for clarity
# ---------------------------------------------------------------------------

def _priority_flood(zt: np.ndarray, cls: np.ndarray, seed: np.ndarray) -> np.ndarray:
    """The improved Priority-Flood (Barnes, Lehman and Mulla 2014), as the
    browser runs it: seeds pushed in grid order keyed by (height, order of
    insertion), a first-in first-out queue for cells raised into a pit.
    Land the flood never reaches has no path to a seed, and is +inf, the
    least over no paths."""
    rows, cols = zt.shape
    height = zt.ravel().tolist()
    closed = (cls != LAND).ravel().tolist()
    heap = []
    seq = 0
    for i in np.flatnonzero(seed.ravel()).tolist():
        closed[i] = True
        heap.append((height[i], seq, i))
        seq += 1
    heapq.heapify(heap)
    pit: deque[int] = deque()
    while heap or pit:
        i = pit.popleft() if pit else heapq.heappop(heap)[2]
        for _, j in _neighbours(i, rows, cols):
            if closed[j]:
                continue
            closed[j] = True
            if height[j] <= height[i]:
                height[j] = height[i]
                pit.append(j)
            else:
                heapq.heappush(heap, (height[j], seq, j))
                seq += 1
    for i, reached in enumerate(closed):
        if not reached:
            height[i] = math.inf
    filled = np.array(height).reshape(rows, cols)
    filled[cls != LAND] = zt[cls != LAND]
    filled[cls == VOID] = nan
    return filled


def _reconstruction(zt: np.ndarray, cls: np.ndarray, seed: np.ndarray) -> np.ndarray:
    """The fill as a morphological reconstruction by erosion: start from the
    seeds' heights and infinity elsewhere, and erode until nothing moves,
    never going below the ground. Cells that are not land pass nothing on."""
    from scipy import ndimage

    land = cls == LAND
    marker = np.where(seed, zt, np.inf)
    marker[~land] = np.inf
    while True:
        eroded = ndimage.grey_erosion(marker, size=(3, 3), mode="constant", cval=np.inf)
        new = np.where(land, np.maximum(zt, np.minimum(marker, eroded)), np.inf)
        if np.array_equal(new, marker):
            break
        marker = new
    filled = zt.copy()
    filled[land] = marker[land]
    filled[cls == VOID] = nan
    return filled


def _barnes_flats(filled: np.ndarray, cls: np.ndarray, code_d8: np.ndarray) -> tuple[np.ndarray, int]:
    """Barnes, Lehman and Mulla (2014) as published: each flat labelled by
    flooding from its low edges, and each flat's own height of the away
    gradient, one cell at a time."""
    rows, cols = filled.shape
    size = rows * cols
    height = filled.ravel().tolist()
    kind = cls.ravel().tolist()
    d8 = code_d8.ravel().tolist()
    noflow = [kind[i] == LAND and d8[i] == 0 for i in range(size)]
    low, high = [], []
    for i in range(size):
        if kind[i] != LAND:
            continue
        if d8[i] != 0:
            if any(noflow[j] and height[j] == height[i] for _, j in _neighbours(i, rows, cols)):
                low.append(i)
        elif any(kind[j] == LAND and height[j] > height[i] for _, j in _neighbours(i, rows, cols)):
            high.append(i)
    label = [0] * size
    labels = 0
    for start in low:
        if label[start]:
            continue
        labels += 1
        label[start] = labels
        queue = deque([start])
        while queue:
            i = queue.popleft()
            for _, j in _neighbours(i, rows, cols):
                if not label[j] and kind[j] == LAND and height[j] == height[start]:
                    label[j] = labels
                    queue.append(j)

    def levels(seeds, visit):
        seen = set(seeds)
        front = list(seeds)
        level = 1
        while front:
            nxt = []
            for i in front:
                visit(i, level)
                for _, j in _neighbours(i, rows, cols):
                    if j not in seen and noflow[j] and label[j] == label[i]:
                        seen.add(j)
                        nxt.append(j)
            front = nxt
            level += 1

    away = [0] * size
    flat_height = [0] * (labels + 1)

    def from_higher(i, level):
        away[i] = level
        flat_height[label[i]] = max(flat_height[label[i]], level)

    levels([i for i in high if label[i]], from_higher)
    mask = [0] * size

    def towards_lower(i, level):
        mask[i] = (flat_height[label[i]] - away[i]) + 2 * level if away[i] else 2 * level

    levels(low, towards_lower)
    code = list(d8)
    unresolved = 0
    for i in range(size):
        if not noflow[i]:
            continue
        best, step = mask[i], -1
        for k, j in _neighbours(i, rows, cols):
            if label[i] and label[j] == label[i] and mask[j] < best:
                best, step = mask[j], k
        if step < 0:
            unresolved += 1
        else:
            code[i] = ESRI[step]
    return np.array(code, dtype=np.uint8).reshape(rows, cols), unresolved


def _accumulate_in_order(code, cls, metric, sea_clean, order: str, seed: int = 0):
    """Counts, areas and flags by Kahn's algorithm one cell at a time,
    taking the ready cells in a random order or newest first."""
    rows, cols = code.shape
    size = rows * cols
    kind = cls.ravel().tolist()
    down = _downstream(code, cls)
    count = [1 if kind[i] == LAND else 0 for i in range(size)]
    area = [int(metric.au_row[i // cols]) if kind[i] == LAND else 0 for i in range(size)]
    flag = [False] * size
    for i in range(size):
        if kind[i] != LAND:
            continue
        r, c = divmod(i, cols)
        near = [kind[j] for _, j in _neighbours(i, rows, cols)]
        flag[i] = (r in (0, rows - 1) or c in (0, cols - 1) or VOID in near
                   or (not sea_clean and SEA in near))
    inflow = [0] * size
    for d in down:
        if d >= 0:
            inflow[d] += 1
    ready = [i for i in range(size) if kind[i] == LAND and inflow[i] == 0]
    rng = np.random.default_rng(seed)
    while ready:
        if order == "random":
            pick = int(rng.integers(len(ready)))
            ready[pick], ready[-1] = ready[-1], ready[pick]
        i = ready.pop()
        d = down[i]
        if d < 0:
            continue
        count[d] += count[i]
        area[d] += area[i]
        flag[d] = flag[d] or flag[i]
        inflow[d] -= 1
        if inflow[d] == 0:
            ready.append(d)
    shape = (rows, cols)
    return (np.array(count, dtype=np.int64).reshape(shape), np.array(area, dtype=np.int64).reshape(shape),
            np.array(flag, dtype=bool).reshape(shape))


RANDOM_GRIDS = [  # (seed, rows, cols, step, relief, voids)
    (1, 30, 40, 0.1, 3.0, 0.03),
    (2, 41, 37, 0.1, 2.0, 0.0),
    (3, 25, 60, 0.5, 4.0, 0.05),
    (4, 50, 45, 1.0, 3.0, 0.02),
    (5, 33, 33, 0.1, 1.0, 0.08),
    (9, 40, 40, 1.0, 3.0, 0.02),
    (32, 40, 40, 1.0, 3.0, 0.02),
]


# ---------------------------------------------------------------------------
# Classes and outlets
# ---------------------------------------------------------------------------

def test_sea_is_low_ground_joined_to_the_edge_and_an_inland_hollow_below_zero_is_not():
    """Prevents two misreadings of sea: an inland hollow below 0 m taken as
    sea (a drainage line would end in the middle of the land), and low
    ground joined to the coast only diagonally, or across a void, read the
    wrong way round."""
    z = np.full((9, 10), 3.0)
    z[0, :6] = [0.0, -1.0, -0.5, 0.0, -2.0, 0.0]   # sea along part of the south edge
    z[1, 6] = 0.0                                  # joined to (0, 5) diagonally only
    z[2, 7] = -0.5                                 # and on, diagonally again
    z[5, 3:5] = [-2.0, 0.0]                        # an inland hollow below sea level
    z[2, 1] = nan                                  # a void ...
    z[3, 1] = -1.0                                 # ... the only link of this cell to the sea
    z[1, 1] = 0.0
    out = _route(z)
    assert out.cls[0, :6].tolist() == [SEA] * 6
    assert out.cls[1, 6] == SEA and out.cls[2, 7] == SEA and out.cls[1, 1] == SEA
    assert out.cls[5, 3] == LAND and out.cls[5, 4] == LAND
    assert out.cls[3, 1] == LAND, "the joining crossed a void"
    assert out.cls[2, 1] == VOID and out.cls[0, 6] == LAND
    assert not out.zero_fill.any()
    # The hollow is filled to the land around it; it is not an outlet.
    assert out.filled[5, 3] == 3.0 and out.filled[5, 4] == 3.0
    assert not out.seed[5, 3] and not out.seed[5, 4]
    # Low land beside the void is an outlet, and keeps its height.
    assert out.seed[3, 1] and out.filled[3, 1] == -1.0
    # Sea keeps its own height; land beside it flows into it.
    assert out.filled[0, 1] == -1.0 and np.isnan(out.filled[2, 1])
    assert out.seed[1, 0] and out.code[1, 0] != 0
    # Sea level is the caller's: at 3 m every cell is at or below it and
    # joins the edge, the hollow too; at -0.25 m the coast's 0 m cells are
    # land, and the hollow, deeper than that, is still not sea.
    cls, _, _, _ = classify_cells(z, 3.0)
    assert (cls[np.isfinite(z)] == SEA).all()
    cls, _, _, _ = classify_cells(z, -0.25)
    assert cls[0, 0] == LAND and cls[0, 1] == SEA and cls[0, 4] == SEA and cls[5, 3] == LAND


def test_a_zero_filled_gap_with_a_straight_edge_is_a_gap_not_sea():
    """Prevents a mosaic's zero-filled missing tile being read as sea about
    a hundred kilometres inland, with drainage lines ending at it, while a
    ragged real coast stays sea; and holds the default to the configured
    straight-edge length."""
    default = inspect.signature(classify_cells).parameters["straight_edge_cells"].default
    assert default == TerrainConfig().sea_straight_edge_cells == 150
    rows, cols, n = 30, 32, 12
    z = 5.0 + np.arange(rows)[:, None] * 0.25 + np.zeros((rows, cols))
    z[:, 24:] = 0.0                               # the gap: 0.0 over the full height, a straight edge
    coast = [2, 3, 1, 3, 2, 4, 2, 1, 3, 2, 4, 3, 1, 2, 3, 2, 1, 3, 4]
    for c, depth in enumerate(coast):              # a ragged sea in the south-west
        z[:depth, c] = -1.0
    for c in range(len(coast), 22):                # land between the two
        z[0, c] = 2.0
    cls, seed, zero_fill, zt = classify_cells(z, 0.0, straight_edge_cells=n)
    assert zero_fill[:, 24:].all() and zero_fill.sum() == rows * 8
    assert (cls[:, 24:] == VOID).all() and np.isnan(zt[:, 24:]).all()
    for c, depth in enumerate(coast):
        assert (cls[:depth, c] == SEA).all() and cls[depth, c] == LAND
    assert seed[:, 23].all(), "land beside the gap is an outlet, as beside any void"
    # The same sea with a straight edge one cell short of the rule stays sea;
    # at the rule's length the whole sea area becomes the gap.
    for length, condemned in ((n - 1, False), (n, True)):
        bay = np.full((10, 20), 4.0)
        bay[:3, :length] = 0.0                     # its north shore runs `length` cells straight
        bay[0, length:length + 4] = -1.0           # an arm of the same sea area, with a short shore
        cls, _, zero_fill, _ = classify_cells(bay, 0.0, straight_edge_cells=n)
        assert bool((cls[:3, :length] == VOID).all()) is condemned
        assert bool((cls[0, length:length + 4] == VOID).all()) is condemned
        assert zero_fill.sum() == (3 * length + 4 if condemned else 0)
        assert bool((cls == SEA).any()) is not condemned
    # A coast along a diagonal is straight too, but no grid line follows it.
    diagonal = np.fromfunction(lambda r, c: np.where(r + c < 20, -1.0, 3.0), (40, 40))
    cls, _, zero_fill, _ = classify_cells(diagonal, 0.0, straight_edge_cells=n)
    assert not zero_fill.any() and (cls[diagonal < 0] == SEA).all()


def test_assumed_sea_is_an_outlet_with_no_height_and_no_slope_beside_it():
    """Prevents a missing tile taken as open sea from being given a height
    (it has none: the drop into it is measured to sea level), from being
    filled or flooded as land, or from cutting a drainage line short of
    the coast."""
    rows, cols = 8, 10
    z = 2.0 + np.arange(cols)[None, :] * -0.1 + np.arange(rows)[:, None] * 0.05 + np.zeros((rows, cols))
    assumed = np.zeros((rows, cols), dtype=bool)
    assumed[:, 7:] = True
    z[assumed] = 99.0                     # whatever is passed there is not a height
    z[3, 6] = 0.0                         # low ground beside the assumed sea joins it
    z[0, 5] = 0.0                         # finite sea on the edge, beside (1, 6)
    out = _route(z, assumed_sea=assumed)
    assert (out.cls[assumed] == SEA).all() and out.cls[3, 6] == SEA and out.cls[0, 5] == SEA
    assert np.isnan(out.zt[assumed]).all() and np.isnan(out.filled[assumed]).all()
    assert out.filled[3, 6] == 0.0
    assert out.seed[:, 6][out.cls[:, 6] == LAND].all()
    # Land beside it flows into it: east, the cardinal neighbour, at sea level.
    assert out.code[5, 6] == E
    # The drop is taken to sea level: (1, 6) at 1.45 m has finite sea at
    # 0.0 m to its south-west and assumed sea to its east, and which is the
    # steeper depends only on the level the assumed sea is given.
    h = out.filled[1, 6]
    dx, dg = out.metric.dx[1], out.metric.dg[1]
    level_tie = h - (h - 0.0) * dx / dg
    for level, expected in ((0.0, E), (level_tie + 0.01, SW)):
        code = flow_directions(out.zt, out.filled, out.cls, out.seed, out.metric, level)
        assert code[1, 6] == expected
    # A drainage line runs to the coast and ends there: the last land cell
    # holds what drains through it, and nothing is carried on into the sea.
    assert out.count[5, 6] > 1
    assert (out.count[assumed] == 0).all() and (out.area[assumed] == 0).all()
    # No slope is computed beside assumed sea, because its 3 by 3 window
    # holds no height there.
    p, q, tanb = horn_gradients(out.zt, out.metric)
    assert np.isnan(tanb[:, 6]).all() and np.isnan(p[:, 6]).all() and np.isnan(q[:, 6]).all()


def test_negative_zero_heights_give_the_same_bits_as_positive_zero():
    """Prevents the engines from differing in a zero's sign: the basin fill
    keeps numpy's choice of operand where Priority-Flood copies, so a -0
    seed beside a void once gave a filled -0 in one engine and +0 in the
    other. Heights are canonicalised on entry, so every layer is the same,
    byte for byte, whichever zero came in."""
    cases = {  # the four cases of the review, each a pit beside a seed beside a void
        "A": [[9, 9, 9, 9, 9, 9], [9, nan, 0.0, -0.0, 9, 9], [9, 9, 9, 9, 9, 9]],
        "B": [[9, 9, 9, 9, 9, 9], [9, nan, -0.0, 0.0, 9, 9], [9, 9, 9, 9, 9, 9]],
        "C": [[9, 9, 9, 9, 9, 9], [9, 9, 0.0, -0.0, nan, 9], [9, 9, 9, 9, 9, 9]],
        "D": [[9, 9, 9, 9, 9, 9], [9, 9, -0.0, 0.0, nan, 9], [9, 9, 9, 9, 9, 9]],
    }
    for name, rows in cases.items():
        z = np.array(rows, dtype=np.float64)
        flipped = np.where(z == 0, np.copysign(0.0, -np.copysign(1.0, z)), z)
        positive = np.where(z == 0, 0.0, z)
        digests = set()
        for grid in (z, flipped, positive):
            out = _route(grid)
            zeros = out.filled == 0
            assert zeros.sum() == 2 and not np.signbit(out.filled[zeros]).any(), name
            assert not np.signbit(out.zt[out.zt == 0]).any(), name
            digests.add(_digest(out.cls, out.seed, out.zt, out.filled, out.code_d8, out.code,
                                out.count, out.area, out.flag))
        assert len(digests) == 1, name
    # And at sea level, where a zero decides between land and sea.
    z = np.array([[-0.0, 0.0, 2.0], [0.0, -0.0, 2.0], [3.0, 3.0, 3.0]])
    a = _route(z)
    b = _route(np.abs(z))
    assert _digest(a.cls, a.zt, a.filled, a.code) == _digest(b.cls, b.zt, b.filled, b.code)


# ---------------------------------------------------------------------------
# Filling
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seed, rows, cols, step, relief, voids", RANDOM_GRIDS)
def test_depression_filling_equals_priority_flood_and_morphological_reconstruction(
        seed, rows, cols, step, relief, voids):
    """Prevents the basin-graph fill drifting from the unique spill surface
    the browser's Priority-Flood finds: any difference in a single bit would
    move a direction, and with it a drainage line, in one engine only."""
    z = _random_heights(seed, rows, cols, step, relief, voids)
    assumed = np.zeros(z.shape, dtype=bool)
    if seed % 2:
        assumed[: rows // 3, -4:] = True          # a corner of missing tile taken as sea
    cls, seed_mask, _, zt = classify_cells(z, 0.0, assumed)
    filled = fill_depressions(zt, cls, seed_mask)
    assert (filled[cls == LAND] > zt[cls == LAND]).any(), "the grid has no hollow to fill"
    assert filled.tobytes() == _priority_flood(zt, cls, seed_mask).tobytes()
    assert filled.tobytes() == _reconstruction(zt, cls, seed_mask).tobytes()


def test_filling_never_lowers_a_cell_and_never_raises_a_seed():
    """Prevents a fill that cuts into the ground or lifts an outlet, either
    of which would send water uphill or strand it; and one that leaves a
    pit, which would end a drainage line inland."""
    for seed, rows, cols, step, relief, voids in RANDOM_GRIDS:
        z = _random_heights(seed, rows, cols, step, relief, voids)
        cls, seeds, _, zt = classify_cells(z, 0.0)
        filled = fill_depressions(zt, cls, seeds)
        land = cls == LAND
        assert (filled[land] >= zt[land]).all()
        assert filled[seeds].tobytes() == zt[seeds].tobytes()
        assert filled[cls == SEA].tobytes() == zt[cls == SEA].tobytes()
        assert np.isnan(filled[cls == VOID]).all()
        # Filling the filled surface changes nothing, and no land cell is
        # left lower than all its land neighbours unless it is an outlet.
        assert fill_depressions(filled, cls, seeds).tobytes() == filled.tobytes()
        for i in np.flatnonzero((land & ~seeds).ravel()).tolist():
            r, c = divmod(i, cols)
            assert any(filled.flat[j] <= filled[r, c] for _, j in _neighbours(i, rows, cols))


def test_filling_follows_its_definition_for_a_seed_mask_of_a_callers_own():
    """fill_depressions is public, and the browser's twin takes any seed
    mask, so the fill must keep to its definition - the least, over paths
    through land to a seed, of the highest cell on the path - whatever
    seeds it is given, not only those classify_cells gives. Prevents a land
    cell beside lower sea that is not a seed draining its hollow out
    through the sea (the basin descent once stepped onto sea), and land
    that no seed can reach coming out at its own height in one engine and
    +inf in the other: each is held here to the Priority-Flood and the
    reconstruction, which follow the definition cell by cell."""
    # no seed at all: no land has a path to one
    zt = np.array([[5.0, 4.0, 3.0, 6.0], [2.0, 1.0, 2.0, 7.0], [5.0, 4.0, 3.0, 6.0]])
    cls = np.full(zt.shape, LAND, dtype=np.uint8)
    assert np.isposinf(fill_depressions(zt, cls, np.zeros(zt.shape, dtype=bool))).all()
    # a hollow beside lower sea, with the only seed at the far corner: the
    # sea is no way out, so the hollow fills to the seed's 9 m
    zt = np.array([[9.0, 8.0, 7.0, 6.0], [9.0, 3.0, 4.0, 0.0], [9.0, 9.0, 9.0, 0.0]])
    cls = np.full(zt.shape, LAND, dtype=np.uint8)
    cls[1:, 3] = SEA
    seed = np.zeros(zt.shape, dtype=bool)
    seed[0, 0] = True
    filled = fill_depressions(zt, cls, seed)
    assert filled.tolist() == [[9.0, 9.0, 9.0, 9.0], [9.0, 9.0, 9.0, 0.0], [9.0, 9.0, 9.0, 0.0]]
    # two land areas parted by a sea column, one of them seeded
    zt = np.array([[5.0, 2.0, 0.0, 6.0, 3.0], [5.0, 1.0, 0.0, 6.0, 2.0], [5.0, 5.0, 0.0, 6.0, 6.0]])
    cls = np.full(zt.shape, LAND, dtype=np.uint8)
    cls[:, 2] = SEA
    seed = np.zeros(zt.shape, dtype=bool)
    seed[2, 0] = True
    filled = fill_depressions(zt, cls, seed)
    assert (filled[:, :2] == 5.0).all() and np.isposinf(filled[:, 3:]).all() and (filled[:, 2] == 0.0).all()
    # On random grids, with seeds scattered sparsely over the land, a single
    # seed in a corner, and seeds only along the edge (sea beside land left
    # unseeded): the same bits as both cell-by-cell methods.
    from scipy import ndimage

    rng = np.random.default_rng(41_7)
    unreached = beside_sea = 0
    for seed_no, rows, cols, step, relief, voids in RANDOM_GRIDS:
        z = _random_heights(seed_no, rows, cols, step, relief, voids)
        cls, _, _, zt = classify_cells(z, 0.0)
        land = cls == LAND
        near_sea = land & ndimage.binary_dilation(cls == SEA, structure=np.ones((3, 3), dtype=bool))
        corner = np.zeros(z.shape, dtype=bool)
        corner[np.unravel_index(np.flatnonzero(land.ravel())[-1], z.shape)] = True
        edge = np.zeros(z.shape, dtype=bool)
        edge[0, :] = edge[-1, :] = edge[:, 0] = edge[:, -1] = True
        for seeds in (land & (rng.random(z.shape) < 0.01), corner, land & edge):
            filled = fill_depressions(zt, cls, seeds)
            assert filled.tobytes() == _priority_flood(zt, cls, seeds).tobytes()
            assert filled.tobytes() == _reconstruction(zt, cls, seeds).tobytes()
            unreached += int(np.isposinf(filled[land]).sum())
            beside_sea += int((near_sea & ~seeds).sum())
    assert unreached > 20 and beside_sea > 1000, "the masks should leave land unreached and sea's neighbours unseeded"


# ---------------------------------------------------------------------------
# Directions
# ---------------------------------------------------------------------------

def _three_by_three(centre: float, around: dict[int, float], base: float = 20.0):
    """A 3 by 3 grid of land with the given heights around the centre, by
    ESRI code, and a 3-4-5 metric so that equal drops can be exact."""
    z = np.full((3, 3), base)
    z[1, 1] = centre
    for code, height in around.items():
        k = ESRI.index(code)
        z[1 + DR[k], 1 + DC[k]] = height
    metric = RowMetric(dx=np.full(3, 3.0), dy=np.full(3, 4.0), dg=np.full(3, 5.0),
                       au_row=np.full(3, 1200, dtype=np.int64))
    cls = np.full((3, 3), LAND, dtype=np.uint8)
    seed = np.ones((3, 3), dtype=bool)
    seed[1, 1] = False
    return z, cls, seed, metric


def test_flow_goes_to_the_steepest_neighbour_and_ties_go_to_cardinals_first():
    """Prevents a direction taken by height difference alone (a diagonal
    neighbour is farther away), by a drop that is not strictly the
    steepest, or by a tie broken in another order than the browser's:
    E, S, W, N, then SE, SW, NW, NE."""
    cases = [  # (centre, heights around it, expected code)
        (10.0, {E: 7.0, S: 6.0}, E),            # 3/3 == 4/4: E comes first
        (10.0, {S: 6.0, SE: 5.0}, S),           # 4/4 == 5/5: the cardinal
        (10.0, {N: 6.0, SE: 5.0}, N),           # N, a cardinal, before SE
        (10.0, {SW: 5.0, NE: 5.0}, SW),         # SW before NE
        (10.0, {E: 7.3, NE: 4.5}, NE),          # 0.9 against 1.1: the diagonal is steeper
        (10.0, {W: 9.0, N: 8.0}, N),            # 1/3 against 2/4
        (10.0, {W: 7.0, S: 5.5}, S),            # 1.0 against 1.125
        (10.0, {}, 0),                          # nothing lower: a flat, left to resolve_flats
    ]
    for centre, around, expected in cases:
        z, cls, seed, metric = _three_by_three(centre, around)
        code = flow_directions(z, z, cls, seed, metric, 0.0)
        assert code[1, 1] == expected, (centre, around)
    # A seed with no lower neighbour flows out of the analysis.
    z, cls, seed, metric = _three_by_three(30.0, {})
    code = flow_directions(z, z, cls, seed, metric, 0.0)
    assert code[1, 1] == E and (code[seed] == 255).all()
    # A void is never a neighbour, however it compares, and is given no
    # direction; sea offers its own height.
    z, cls, seed, metric = _three_by_three(1.0, {E: 0.5, W: 0.2})
    cls[1, 0] = VOID
    z[1, 0] = nan
    code = flow_directions(z, z, cls, seed, metric, 0.0)
    assert code[1, 1] == E and code[1, 0] == 0
    cls[1, 2] = SEA
    z[1, 2] = -30.0
    code = flow_directions(z, z, cls, seed, metric, 0.0)
    assert code[1, 1] == E and code[2, 2] == S and code[0, 2] == N and code[1, 2] == 0
    # The distances are the origin row's own.
    z = np.array([[5.0, 5.0, 5.0], [5.0, 6.0, 5.0], [5.0, 5.0, 5.0]])
    metric = RowMetric(dx=np.array([3.0, 4.0, 3.0]), dy=np.array([4.0, 3.0, 4.0]),
                       dg=np.full(3, 5.0), au_row=np.full(3, 1200, dtype=np.int64))
    cls = np.full((3, 3), LAND, dtype=np.uint8)
    code = flow_directions(z, z, cls, np.ones((3, 3), dtype=bool), metric, 0.0)
    assert code[1, 1] == S, "row 1's dy (3 m) is shorter than its dx (4 m)"


def _d8_reference(zt, filled, cls, seed, metric, sea_level: float) -> np.ndarray:
    """D8 as spec 3.7 writes it, one cell at a time: a neighbour counts only
    when it is lower, and of those the steepest drop wins, the first in K
    on a tie."""
    rows, cols = filled.shape
    code = np.zeros((rows, cols), dtype=np.uint8)
    for r in range(rows):
        dist = (metric.dx[r], metric.dy[r], metric.dx[r], metric.dy[r], *[metric.dg[r]] * 4)
        for c in range(cols):
            if cls[r, c] != LAND:
                continue
            here, best, bk = float(filled[r, c]), 0.0, -1
            for k, j in _neighbours(r * cols + c, rows, cols):
                rr, cc = divmod(j, cols)
                if cls[rr, cc] == VOID:
                    continue
                there = float(filled[rr, cc] if cls[rr, cc] == LAND else
                              (zt[rr, cc] if math.isfinite(zt[rr, cc]) else sea_level))
                drop = (here - there) / float(dist[k])
                if here > there and (bk < 0 or drop > best):
                    best, bk = drop, k
            code[r, c] = ESRI[bk] if bk >= 0 else (255 if seed[r, c] else 0)
    return code


def test_a_drop_that_underflows_to_zero_still_counts_as_a_way_down():
    """Prevents a pit left after the fill: two heights a few multiples of
    2**-1074 apart differ by an amount that, divided by some thirty metres,
    rounds to +0, and a D8 that asked for a positive drop took the cell
    beside the outlet for a flat with no way out, so the whole floor
    drained into its middle and a line ended there as a "sink". Lower is
    now decided on the heights. The floors here are subnormal heights, then
    normal ones (1e-307 and the next double up), and then a coast where a
    land cell a subnormal above sea level must flow into the sea (W), not
    out of the analysis (255)."""
    def floor(base: float, outlet: float) -> np.ndarray:
        z = np.full((5, 5), 10.0)
        z[1:4, 1:4] = base
        z[0, 2] = outlet
        return z

    for z in (floor(5e-324, 0.0), floor(math.nextafter(1e-307, math.inf), 1e-307)):
        out = _route(z, sea_level=-1.0)
        assert out.unresolved == 0
        assert out.code_d8[1, 2] == S, "the cell beside the outlet has a way down"
        assert out.code_d8.tobytes() == _d8_reference(out.zt, out.filled, out.cls, out.seed, out.metric,
                                                      -1.0).tobytes()
        down = _downstream(out.code, out.cls)
        for i in (r * 5 + c for r in range(1, 4) for c in range(1, 4)):
            while down[i] >= 0:
                i = down[i]
            assert i == 2, "every cell of the floor drains to the outlet"
        assert analyse_terrain(_elevation(z), TerrainConfig(sea_level_m=-1.0), precision="float64").unresolved == 0
    z = np.full((3, 4), 10.0)
    z[:, 0] = 0.0
    z[1, 1] = 5e-324
    out = _route(z)
    assert (out.cls[:, 0] == SEA).all() and out.cls[1, 1] == LAND and out.seed[1, 1]
    assert out.code_d8[1, 1] == W, "into the sea a subnormal below it, not out of the analysis"
    # On the random grids, whose drops never underflow, the rule written
    # out cell by cell gives the same directions.
    for seed, rows, cols, step, relief, voids in RANDOM_GRIDS:
        out = _route(_random_heights(seed, rows, cols, step, relief, voids))
        assert out.code_d8.tobytes() == _d8_reference(out.zt, out.filled, out.cls, out.seed, out.metric,
                                                      0.0).tobytes()


@pytest.mark.parametrize("seed, rows, cols, step, relief, voids", RANDOM_GRIDS)
def test_every_flat_cell_gets_a_direction_towards_its_outlet(seed, rows, cols, step, relief, voids):
    """Prevents a flat cell left without a direction (its area would never
    reach a drainage line), a cycle across a flat, or a route that climbs:
    every land cell's path runs downhill or level to an outlet, and across
    a flat leaves it by a cell that has a way down."""
    out = _route(_random_heights(seed, rows, cols, step, relief, voids))
    land = out.cls == LAND
    flats = land & (out.code_d8 == 0)
    assert flats.sum() > 20, "the grid has too few flat cells to test"
    assert out.unresolved == 0 and (out.code[land] != 0).all()
    assert (out.code[~flats] == out.code_d8[~flats]).all()
    down = _downstream(out.code, out.cls)
    heights = out.filled.ravel().tolist()
    for i in np.flatnonzero(land.ravel()).tolist():
        seen = {i}
        j = i
        while down[j] >= 0:
            assert heights[down[j]] <= heights[j]
            if flats.flat[i] and heights[j] == heights[i] and heights[down[j]] < heights[i]:
                assert out.code_d8.flat[j] != 0, "a flat was left by a cell with no way down"
            j = down[j]
            assert j not in seen, "a cycle"
            seen.add(j)
        assert out.code.flat[j] == 255 or out.code.flat[j] in ESRI


@pytest.mark.parametrize("seed, rows, cols, step, relief, voids", RANDOM_GRIDS)
def test_flat_directions_equal_barnes_with_per_flat_labels(seed, rows, cols, step, relief, voids):
    """Prevents the one-constant form of Barnes's method (the same in both
    engines, and cheap) from drifting from the method as published, with
    each flat labelled and given its own height."""
    out = _route(_random_heights(seed, rows, cols, step, relief, voids))
    expected, unresolved = _barnes_flats(out.filled, out.cls, out.code_d8)
    assert unresolved == 0 == out.unresolved
    assert (out.code != out.code_d8).sum() > 20, "the grid has too few flat cells to test"
    assert out.code.tobytes() == expected.tobytes()


def test_a_flat_drains_away_from_higher_ground_as_barnes_describes():
    """Prevents a flat drained by the distance to its outlet alone, which
    runs water along the foot of the slopes that bound it in parallel
    lines; Barnes's away gradient sends it down the middle first."""
    rows, cols = 9, 16
    z = np.full((rows, cols), 10.0)
    z[2:7, 1:15] = 5.0                        # a flat valley floor between higher ground
    z[4, 15] = 4.0                            # its one outlet, at the east end
    out = _route(z)
    floor = (slice(2, 7), slice(1, 15))
    assert (out.filled[floor] == 5.0).all() and out.unresolved == 0
    code = out.code
    # Far from the outlet, the cells along the foot of the slopes turn in
    # towards the middle, and the middle row runs east.
    assert (code[2, 2:10] == NE).all() and (code[6, 2:10] == SE).all()
    assert (code[4, 2:14] == E).all()
    # (Distance from the outlet alone would have sent every row east.) And
    # everything between the north and south edges still drains to the
    # outlet: the floor, the slopes around it and the outlet itself.
    assert code[4, 14] == E and code[4, 15] == 255
    assert out.count[4, 15] == 7 * cols
    assert out.code.tobytes() == _barnes_flats(out.filled, out.cls, out.code_d8)[0].tobytes()
    # Where the one outlet is a corner, beside the higher ground, the pull
    # towards it, counted twice, still outweighs the push away from the
    # slopes: every cell of the floor, and of the slopes, drains to it.
    z = np.full((11, 11), 10.0)
    z[1:10, 1:10] = 5.0
    z[0, 1] = 4.0
    out = _route(z)
    assert out.unresolved == 0 and out.count[0, 1] == z.size
    assert out.code.tobytes() == _barnes_flats(out.filled, out.cls, out.code_d8)[0].tobytes()


# ---------------------------------------------------------------------------
# Accumulation and contamination
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seed, rows, cols, step, relief, voids", RANDOM_GRIDS)
def test_accumulation_conserves_area_and_every_land_cell_reaches_one_outlet(
        seed, rows, cols, step, relief, voids):
    """Prevents area lost or counted twice: every land cell drains to
    exactly one end, the ends between them hold all the land, and every
    cell holds itself plus exactly what drains into it."""
    out = _route(_random_heights(seed, rows, cols, step, relief, voids))
    land = out.cls == LAND
    assert out.count.dtype == np.int64 and out.area.dtype == np.int64 and out.flag.dtype == bool
    assert (out.count[~land] == 0).all() and (out.area[~land] == 0).all() and not out.flag[~land].any()
    down = _downstream(out.code, out.cls)
    cell_area = np.broadcast_to(out.metric.au_row[:, None], land.shape)
    ends = set()
    for i in np.flatnonzero(land.ravel()).tolist():
        j, steps = i, 0
        while down[j] >= 0:
            j, steps = down[j], steps + 1
            assert steps <= land.size, "a cycle"
        ends.add(j)
    ends_list = sorted(ends)
    assert out.count.ravel()[ends_list].sum() == land.sum()
    assert out.area.ravel()[ends_list].sum() == cell_area[land].sum()
    inflow_count = np.zeros(land.size, dtype=np.int64)
    inflow_area = np.zeros(land.size, dtype=np.int64)
    for i, d in enumerate(down):
        if d >= 0:
            inflow_count[d] += out.count.flat[i]
            inflow_area[d] += out.area.flat[i]
    assert (out.count.ravel()[land.ravel()] == 1 + inflow_count[land.ravel()]).all()
    assert (out.area.ravel()[land.ravel()] == cell_area.ravel()[land.ravel()] + inflow_area[land.ravel()]).all()


def test_area_sums_do_not_depend_on_the_order_cells_are_visited():
    """Prevents an area that moves in its last bits with the order cells
    are visited, which would set the two engines apart at the stream
    threshold: areas are whole units of 0.01 square metres, added exactly
    in any order."""
    for seed, rows, cols, step, relief, voids in RANDOM_GRIDS:
        out = _route(_random_heights(seed, rows, cols, step, relief, voids))
        for sea_clean in (True, False):
            mine = accumulate_flow(out.code, out.cls, out.metric, sea_clean)
            for order in ("random", "newest"):
                theirs = _accumulate_in_order(out.code, out.cls, out.metric, sea_clean, order, seed)
                for a, b in zip(mine, theirs, strict=True):
                    assert a.tobytes() == b.tobytes()
    # The units are integers that float64 holds exactly at the cap: two
    # million of the largest 1 arc-second cells there are, at the equator.
    assert 2_000_000 * int(_metric(2, 2, lat=0.0).au_row.max()) < 2 ** 53


def test_contamination_flows_downstream_from_the_edge_and_voids_but_not_from_known_sea():
    """Prevents an area that may be short or long being drawn as certain:
    a cell on the edge or beside a void is flagged, and so is everything
    downstream of it; sea flags only for a source not known to write sea
    as 0 m, where an undetected fill may hide land."""
    rows, cols = 12, 9
    z = 1.0 + np.arange(rows)[:, None] * 1.0 + np.zeros((rows, cols))   # a plane falling to the south
    z[0, :] = -1.0                              # the sea along the south edge
    z[rows - 1, :] = rows - 3.0                 # a ridge one row in from the north edge
    z[7, 4] = nan                               # a void in the middle
    out = _route(z)
    land = out.cls == LAND
    southward = land.copy()
    southward[[0, rows - 2, rows - 1], :] = False
    southward[8, 4] = False                     # above the void, which turns it aside
    assert (out.code[southward] == S).all() and out.code[8, 4] == SE
    flag = out.flag
    assert flag[land[:, 0], 0].all() and flag[land[:, -1], -1].all() and flag[rows - 1, 1:-1].all()
    assert flag[1:7, 4].all(), "downstream of the void"
    assert flag[1:9, 3].all() and flag[1:9, 5].all(), "beside the void, and downstream of that"
    assert not flag[1:rows - 1, 1:3].any() and not flag[1:rows - 1, 6:8].any(), \
        "land beside known sea, draining nothing from the edge or a void, is flagged"
    unstated = accumulate_flow(out.code, out.cls, out.metric, False)[2]
    assert unstated[1, 1:cols - 1].all() and not unstated[2:rows - 2, 1:3].any()
    # Against the rule written out: flagged exactly when some cell draining
    # to it (itself included) is on the edge, beside a void, or beside sea
    # of unstated source.
    for seed, rows_, cols_, step, relief, voids in RANDOM_GRIDS:
        r = _route(_random_heights(seed, rows_, cols_, step, relief, voids))
        for sea_clean in (True, False):
            flag = accumulate_flow(r.code, r.cls, r.metric, sea_clean)[2]
            assert flag.tobytes() == _accumulate_in_order(r.code, r.cls, r.metric, sea_clean, "newest")[2].tobytes()


def test_flow_directions_that_go_round_in_a_loop_are_refused():
    """Prevents totals that come back short without a word: Kahn's order
    never reaches a cell on a loop of directions, so the loop's cells, and
    every cell draining into them, would keep only part of their area. The
    routing never makes a loop, but accumulate_flow is public and takes any
    directions, and a loop once came out of a grid whose axes descended.
    Broken in one place, the same directions give exact totals."""
    cls = np.full((3, 3), LAND, dtype=np.uint8)
    code = np.full((3, 3), 255, dtype=np.uint8)
    code[0, 0], code[0, 1], code[1, 1], code[1, 0] = E, N, W, S      # round a square of four cells
    code[2, 2] = SW                                                  # and a cell draining into it
    metric = _metric(3, 3)
    with pytest.raises(ValueError, match="^the flow directions form a loop$"):
        accumulate_flow(code, cls, metric, True)
    code[1, 0] = 255
    count, area, _ = accumulate_flow(code, cls, metric, True)
    assert count[1, 0] == 5 and count[1, 1] == 4 and count[0, 1] == 2
    assert area[1, 0] == 2 * metric.au_row[0] + 2 * metric.au_row[1] + metric.au_row[2]


def test_importing_the_analysis_does_not_import_pyplot():
    """Prevents the terrain analysis pulling in matplotlib, or scipy at
    import, which the browser's Pyodide build and the import bench would
    both pay for before a terrain was ever analysed."""
    code = (
        "import sys\n"
        "import numpy as np\n"
        "from groundwater.mapping import terrain_analysis as ta\n"
        "print(sorted(m for m in sys.modules if m.split('.')[0] in ('matplotlib', 'scipy')))\n"
        "z = np.array([[3.0, 2.0, 3.0], [3.0, 1.0, 3.0], [3.0, 0.0, 3.0]])\n"
        "cls, seed, _, zt = ta.classify_cells(z, -1.0)\n"
        "print(ta.fill_depressions(zt, cls, seed)[1, 1],\n"
        "      sorted(m for m in sys.modules if m.split('.')[0] == 'matplotlib'))\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert result.stdout.splitlines() == ["[]", "1.0 []"]


# ---------------------------------------------------------------------------
# The analysis assembled: drainage lines, the summary, storage and captions
# ---------------------------------------------------------------------------

DEM = Path(__file__).resolve().parent / "webapp" / "fixtures" / "dem"
COPERNICUS_PAIR = ("Copernicus_DSM_COG_10_N08_00_W012_00_DEM.tif", "Copernicus_DSM_COG_10_N08_00_W011_00_DEM.tif")
#: A threshold a little under the area of one 1 arc-second cell at 8.5
#: degrees north (about 94,000 units of 0.01 m²), so that every land cell
#: of a core drawn by hand is a stream cell.
ONE_CELL_KM2 = 0.0005
#: About three cells: thresholds low enough for a small grid to hold lines.
SMALL_KM2 = 0.003


def _elevation(z, lat: float = 8.5, step: float = 1 / 3600, **kwargs) -> ElevationGrid:
    """A grid on the lattice ``_metric`` measures (south row at ``lat``),
    from a source that writes the sea as 0 m unless ``sea_clean`` is given."""
    z = np.asarray(z, dtype=np.float64)
    rows, cols = z.shape
    kwargs.setdefault("sea_clean", True)
    return ElevationGrid(-12.0 + np.arange(cols) * step, lat + np.arange(rows) * step, z, **kwargs)


def _drawn(rows: int, cols: int, paths, sea=(), flat=(), raised=(), shown=None) -> TerrainCore:
    """A core drawn by hand. The cells of ``paths`` are land, each pointing
    to the next cell of its path; a path's last cell flows out of the
    analysis unless another path takes it on or it is in ``sea``. Every
    other cell is a void. ``flat`` and ``raised`` list the cells marked as
    routed across a flat and as raised by the fill."""
    cls = np.full((rows, cols), VOID, dtype=np.uint8)
    code = np.zeros((rows, cols), dtype=np.uint8)
    for path in paths:
        for cell in path:
            cls[cell] = LAND
    for cell in sea:
        cls[cell] = SEA
    steps = list(zip(DR, DC, strict=True))
    for path in paths:
        for (r, c), (rr, cc) in zip(path, path[1:], strict=False):
            code[r, c] = ESRI[steps.index((rr - r, cc - c))]
    code[(cls == LAND) & (code == 0)] = 255
    metric = _metric(rows, cols)
    count, area, flag = accumulate_flow(code, cls, metric, True)
    marks = {}
    for name, cells in (("flat_routed", flat), ("raised", raised)):
        mask = np.zeros((rows, cols), dtype=bool)
        for cell in cells:
            mask[cell] = True
        marks[name] = mask
    return TerrainCore(rows=rows, cols=cols, shown=shown or (0, rows, 0, cols),
                       lons=-12.0 + np.arange(cols) * (1 / 3600), lats=8.5 + np.arange(rows) * (1 / 3600),
                       dx=metric.dx, dy=metric.dy, dg=metric.dg, cls=cls, code=code, flag=flag,
                       count=count, area_units=area, **marks)


def _links_as_written(core: TerrainCore, area_km2: float):
    """The drainage lines and their parts as the design writes them out,
    one cell at a time on plain lists: an oracle for drainage_links, which
    walks the stream cells alone on arrays of its own."""
    rows, cols = core.rows, core.cols
    size = rows * cols
    threshold = math.floor(area_km2 * 1e8 + 0.5)
    kind = core.cls.ravel().tolist()
    code = core.code.ravel().tolist()
    au = core.area_units.ravel().tolist()
    cnt = core.count.ravel().tolist()
    flag = core.flag.ravel().tolist()
    raised = core.raised.ravel().tolist()
    flat = core.flat_routed.ravel().tolist()
    down = _downstream(core.code, core.cls)
    stream = [kind[i] == LAND and au[i] >= threshold for i in range(size)]
    sd = [0] * size
    for i in range(size):
        if stream[i] and down[i] >= 0:
            sd[down[i]] += 1
    starts = [i for i in range(size) if stream[i] and (sd[i] == 0 or sd[i] >= 2)]

    def rc(i):
        return divmod(i, cols)

    def dist(i):
        k = ESRI.index(code[i])
        sizes = (core.dx, core.dy, core.dx, core.dy, core.dg, core.dg, core.dg, core.dg)[k]
        return float(sizes[i // cols])

    def key(i):
        return code[i], flat[i]

    def vertices(p):
        if len(p) == 1:
            return [p[0]]
        return [p[0]] + [p[m] for m in range(1, len(p) - 1) if key(p[m]) != key(p[m - 1])] + [p[-1]]

    def length(p):
        total = 0.0
        for m in range(len(p) - 1):
            total += dist(p[m])
        return total

    traced = []
    for s in starts:
        cells, cur = [s], s
        while True:
            d = down[cur]
            if d >= 0:
                if sd[d] >= 2:
                    terminal, outlet = d, "confluence"
                    break
                cells.append(d)
                cur = d
            elif code[cur] == 255:
                r, c = rc(cur)
                terminal, outlet = None, ("edge" if r in (0, rows - 1) or c in (0, cols - 1) else "void")
                break
            elif code[cur] == 0:
                terminal, outlet = None, "sink"
                break
            else:
                k = ESRI.index(code[cur])
                r, c = rc(cur)
                terminal, outlet = (r + DR[k]) * cols + c + DC[k], "sea"
                break
        positions = cells + ([terminal] if terminal is not None else [])
        traced.append((cells, positions, outlet, starts.index(terminal) if outlet == "confluence" else -1))

    order = {}
    for n in sorted(range(len(starts)), key=lambda n: (cnt[starts[n]], starts[n])):
        incoming = [order[m] for m, t in enumerate(traced) if t[3] == n]
        top = max(incoming, default=0)
        order[n] = 1 if not incoming else (top + 1 if incoming.count(top) >= 2 else top)

    r0, r1, c0, c1 = core.shown
    links, parts = [], []
    for n, (cells, positions, outlet, downstream) in enumerate(traced):
        links.append(DrainageLink(
            id=n, start=starts[n], vertices=tuple(rc(x) for x in vertices(positions)), cells=len(cells),
            outlet=outlet, downstream=downstream, strahler=order[n], area_units=au[cells[-1]],
            length_m=length(positions), edge_contaminated=flag[cells[-1]],
            filled_cells=sum(raised[x] for x in cells), flat_routed_cells=sum(flat[x] for x in cells)))
        runs, run = [], []
        for x in positions:
            r, c = rc(x)
            if r0 <= r < r1 and c0 <= c < c1:
                run.append(x)
            elif run:
                runs.append(run)
                run = []
        if run:
            runs.append(run)
        for part, p in enumerate(run for run in runs if len(run) > 1):
            own = [x for x in p if x in cells]
            v = vertices(p)
            parts.append(DrainagePart(
                id=n, part=part, vertices=tuple(rc(x) for x in v), stretch_flat=tuple(flat[x] for x in v[:-1]),
                outlet=outlet if p[-1] == positions[-1] else "beyond_view", strahler=order[n],
                downstream=downstream, area_units=au[own[-1]], length_m=length(p),
                edge_contaminated=flag[own[-1]], filled_cells=sum(raised[x] for x in own),
                flat_routed_cells=sum(flat[x] for x in own)))
    return tuple(links), tuple(parts)


def _layers(a) -> list[np.ndarray]:
    """Every layer of an analysis, the core's included."""
    core = a.core
    return [a.filled, a.fill_depth, a.stream, a.p, a.q, a.tanb, *a.hillshades, a.hillshade_multi, a.twi_arg,
            a.twi, a.profile, a.tangential, core.cls, core.code, core.flag, core.raised, core.flat_routed,
            core.count, core.area_units, core.lons, core.lats, core.dx, core.dy, core.dg]


def _fingerprint(a) -> str:
    """Everything an analysis says, as one string: the layers' bytes, the
    lines and the summary."""
    return _digest(*_layers(a)) + repr((a.links, a.parts, a.summary, a.k_cells, a.unresolved))


def _meta(core: TerrainCore, **overrides) -> dict:
    """What drainage_geojson is told about a window, with some made-up
    values a test can override."""
    centre = WindowCentre(float(core.lons[core.cols // 2]), float(core.lats[core.rows // 2]), "Kakua", True)
    meta = {"label": "elevation model test.tif, source not stated", "credit": "", "notice": None,
            "surface": phrase("terrain.surface_unknown"), "area": SMALL_KM2, "radius": 1.0, "margin": 0.5,
            "centre": centre}
    meta.update(overrides)
    return meta


def _parsed(text: str):
    """GeoJSON text parsed with every number kept as the text it was written as."""
    return json.loads(text, parse_float=str, parse_int=str)


def test_an_analysis_refuses_a_grid_whose_axes_do_not_ascend():
    """Prevents water sent uphill: with both axes running the other way
    (an .asc file with a negative cell size, or a grid built north-first
    through the API) every cell size comes out negative, each cardinal drop
    turns round, the directions go round in loops, and 21,000 of 40,000
    cells once drained to higher ground with nothing reported; with only
    the latitudes reversed the totals refused with a sentence about whole
    units of area; and an axis with no step gives cells of no size. Each
    is refused in the catalogue's words. row_metric and the shading still
    take a descending grid, on which they are right: the hillshade of the
    reversed grid, turned back, is the hillshade of the grid."""
    from groundwater.mapping.terrain import hillshade, slope_percent

    z = _random_heights(4, 50, 45, 1.0, 3.0, 0.02)
    grid = _elevation(z)
    lons, lats = grid.lons, grid.lats
    refused = {
        "both axes descending": ElevationGrid(lons[::-1].copy(), lats[::-1].copy(), z[::-1, ::-1].copy()),
        "latitudes descending": ElevationGrid(lons, lats[::-1].copy(), z[::-1].copy()),
        "no step between columns": ElevationGrid(np.full(lons.size, lons[0]), lats, z),
    }
    for label, bad in refused.items():
        with pytest.raises(ValueError) as caught:
            analyse_terrain(bad, precision="float64")
        assert str(caught.value) == phrase("terrain.axes_descend"), label
    # an axis whose last centre is not a number has no cell size at all,
    # which row_metric itself refuses here (the browser's gives NaN sizes,
    # which the analysis refuses in the words above)
    with pytest.raises(ValueError):
        analyse_terrain(ElevationGrid(np.r_[lons[:-1], nan], lats, z), precision="float64")
    reversed_grid = refused["both axes descending"]
    metric = row_metric(reversed_grid.lons, reversed_grid.lats)
    assert (metric.dx < 0).all() and (metric.dy < 0).all()
    assert hillshade(reversed_grid)[::-1, ::-1].tobytes() == hillshade(grid).tobytes()
    assert slope_percent(reversed_grid)[::-1, ::-1].tobytes() == slope_percent(grid).tobytes()


def test_cells_routed_across_flats_and_filled_hollows_are_marked():
    """Prevents a drainage line drawn as if its route were known where the
    fill or the flat resolution chose it: a cell left level by D8 or raised
    by the fill is marked flat_routed, a cell raised by fill_note_m or more
    is marked raised, and the lines count both, so the figures can draw
    those stretches paler and the export can say how many there are."""
    rows, cols = 12, 14
    z = 30.0 - np.arange(cols)[None, :] * 1.0 + np.arange(rows)[:, None] * 0.1 + np.zeros((rows, cols))
    z[3:9, 3:7] = 25.0                       # a level terrace on a slope falling east
    z[9, 10] -= 3.0                          # a hollow filled by about 2 m
    z[2, 10] -= 1.5                          # and one filled by about 0.4 m
    a = analyse_terrain(_elevation(z), TerrainConfig(drainage_area_km2=SMALL_KM2), precision="float64")
    out = _route(z)
    land = out.cls == LAND
    depth = np.where(land, out.filled - out.zt, nan)
    assert (a.core.flat_routed == (land & ((out.code_d8 == 0) | (depth > 0)))).all()
    assert (a.core.raised == (land & (depth >= 1.0))).all()
    assert a.fill_depth.tobytes() == depth.tobytes()
    # The terrace's cells with no way down are routed across it; its east
    # edge, which drops to the slope below, is routed by slope.
    assert a.core.flat_routed[4:8, 4:6].all() and not a.core.flat_routed[3:9, 6].any()
    assert a.core.flat_routed[9, 10] and a.core.raised[9, 10] and depth[9, 10] > 1.0
    assert a.core.flat_routed[2, 10] and not a.core.raised[2, 10] and 0.0 < depth[2, 10] < 1.0
    assert a.core.raised.sum() == 1 and not a.core.flat_routed[land & (out.code_d8 != 0) & (depth == 0)].any()
    # Each stream cell is one line's own, so the lines' counts add up to the
    # marked stream cells, and every stretch is marked by its first vertex.
    stream = a.stream
    assert sum(link.flat_routed_cells for link in a.links) == (stream & a.core.flat_routed).sum() > 0
    assert sum(link.filled_cells for link in a.links) == (stream & a.core.raised).sum()
    assert any(any(part.stretch_flat) for part in a.parts) and not all(all(p.stretch_flat) for p in a.parts)
    for part in a.parts:
        assert part.stretch_flat == tuple(bool(a.core.flat_routed[v]) for v in part.vertices[:-1])
    summary = a.summary
    assert summary["raised"] == 1 and summary["raised_pct"] == (100.0 * 1) / land.sum()
    assert summary["flat_routed_stream"] == (stream & a.core.flat_routed).sum()
    assert summary["flat_routed_lines_pct"] == (100.0 * summary["flat_routed_stream"]) / summary["stream"]
    assert summary["max_fill_m"] == depth[9, 10]


def test_sea_in_a_file_of_unstated_source_marks_lines_as_uncertain():
    """Prevents a line ending at what may be a 0 m fill value, in a file
    whose source does not say it writes the sea as 0 m, from being drawn as
    certain: its upslope area may continue under the fill. A source that
    does say so (Copernicus, SRTM) leaves the same lines undashed."""
    rows, cols = 20, 25
    r = np.arange(rows)[:, None]
    c = np.arange(cols)[None, :]
    z = 2.0 + r * 0.5 + np.abs((c % 6) - 3) * 0.3 + np.zeros((rows, cols))   # gullies running south
    z[:, 0] -= 5.0                                        # the west and east edges drain out sideways,
    z[:, -1] -= 5.0                                       # and the north edge drains north,
    z[-1, :] = z[-2, :] - 1.0                             # so no line inside starts on the edge
    z[:2, :] = -1.0                                       # the sea along the south edge
    cfg = TerrainConfig(drainage_area_km2=SMALL_KM2)
    clean = analyse_terrain(_elevation(z, sea_clean=True), cfg)
    unstated = analyse_terrain(_elevation(z, sea_clean=False), cfg)
    assert clean.links == drainage_links(clean.core, SMALL_KM2)[0]

    def inland(a):
        """The lines into the sea that run nowhere near the west or east edge."""
        return [link for link in a.links if link.outlet == "sea" and all(1 < c < cols - 2 for _, c in link.vertices)]

    to_sea, unsure = inland(clean), inland(unstated)
    assert len(to_sea) >= 3 and not any(link.edge_contaminated for link in to_sea)
    assert [link.vertices for link in unsure] == [link.vertices for link in to_sea]
    assert all(link.edge_contaminated for link in unsure)
    assert all(part.edge_contaminated for part in unstated.parts if part.outlet == "sea")
    assert unstated.summary["contaminated_stream"] > clean.summary["contaminated_stream"]
    # Only the flags differ: the routing does not depend on the sea rule.
    assert (clean.core.code == unstated.core.code).all()
    assert (clean.core.area_units == unstated.core.area_units).all()
    sentence = phrase("terrain.caption_sea_unstated", level=0.0)
    assert sentence in terrain_captions(unstated, None, "Bonthe")["relief"]
    assert sentence not in terrain_captions(clean, None, "Bonthe")["relief"]


def _hand_network() -> TerrainCore:
    """Fifteen lines drawn by hand on a 14 by 16 grid, each cell named by
    (row, column) with north at row + 1: a main stem along row 4 leaving by
    the east edge, joined by single tributaries, by two at once, by a
    second-order tributary, and by three first-order lines that meet at one
    cell first."""
    main = [(4, c) for c in range(1, 16)]
    paths = [
        main,
        [(8, 3), (7, 3), (6, 3), (5, 3), (4, 3)],                 # 1 joins 1 at (4, 3)
        [(8, 6), (7, 6), (6, 6), (5, 6), (4, 6)],                 # 1 and 1 join 2 at (4, 6)
        [(2, 6), (3, 6), (4, 6)],
        [(12, 9), (11, 9), (10, 9), (9, 9), (8, 9)],              # 1 joins 1 at (8, 9) ...
        [(8, 12), (8, 11), (8, 10), (8, 9)],
        [(8, 9), (7, 9), (6, 9), (5, 9), (4, 9)],                 # ... and that 2 joins 2 at (4, 9)
        [(1, 10), (1, 11), (1, 12)],                              # three 1s meet at (1, 12) ...
        [(0, 13), (1, 12)],
        [(1, 14), (1, 13), (1, 12)],
        [(1, 12), (2, 12), (3, 12), (4, 12)],                     # ... and that 2 joins 3 at (4, 12)
    ]
    return _drawn(14, 16, paths)


def test_links_meet_at_confluences_and_strahler_order_rises_only_where_equal_orders_meet():
    """Prevents lines that do not meet where they join, a line counted
    twice or not at all, and a Strahler order that rises at every junction
    (a first-order tributary does not make a river third order) or that
    misses a rise where two equal orders meet, three-way junctions
    included."""
    core = _hand_network()
    links, _ = drainage_links(core, ONE_CELL_KM2)
    start = {divmod(link.start, core.cols): link for link in links}
    assert len(links) == 15 and sorted(start) == [
        (0, 13), (1, 10), (1, 12), (1, 14), (2, 6), (4, 1), (4, 3), (4, 6), (4, 9), (4, 12),
        (8, 3), (8, 6), (8, 9), (8, 12), (12, 9)]
    assert [link.id for link in links] == list(range(15))
    assert [link.start for link in links] == sorted(link.start for link in links), "ids in grid order"
    order = {cell: link.strahler for cell, link in start.items()}
    assert order == {(0, 13): 1, (1, 10): 1, (1, 14): 1, (2, 6): 1, (4, 1): 1, (8, 3): 1, (8, 6): 1, (8, 12): 1,
                     (12, 9): 1,
                     (4, 3): 2,      # 1 + 1
                     (4, 6): 2,      # 2 + 1 + 1: the higher order carries on
                     (8, 9): 2,      # 1 + 1
                     (1, 12): 2,     # 1 + 1 + 1
                     (4, 9): 3,      # 2 + 2
                     (4, 12): 3}     # 3 + 2
    # Every line ends where the line it joins starts, and only a cell that
    # two or more lines run into starts a line other than a headwater.
    joined: dict[int, list[DrainageLink]] = {}
    for link in links:
        if link.outlet == "confluence":
            below = links[link.downstream]
            assert link.vertices[-1] == below.vertices[0]
            joined.setdefault(below.id, []).append(link)
        else:
            assert link.downstream == -1
    assert {cell: len(joined[link.id]) for cell, link in start.items() if link.id in joined} == {
        (4, 3): 2, (4, 6): 3, (8, 9): 2, (1, 12): 3, (4, 9): 2, (4, 12): 2}
    assert [link.outlet for link in links if link.outlet != "confluence"] == ["edge"]
    stem = start[(4, 12)]
    assert stem.vertices == ((4, 12), (4, 15)) and stem.cells == 4
    assert stem.length_m == (core.dx[4] + core.dx[4]) + core.dx[4]
    assert stem.area_units == core.area_units[4, 15] and stem.edge_contaminated
    assert start[(0, 13)].vertices == ((0, 13), (1, 12)) and start[(0, 13)].length_m == core.dg[0]
    # Against the rules written out one cell at a time, by hand and on
    # random grids.
    assert drainage_links(core, ONE_CELL_KM2) == _links_as_written(core, ONE_CELL_KM2)
    for seed, rows, cols, step, relief, voids in RANDOM_GRIDS:
        z = _random_heights(seed, rows, cols, step, relief, voids)
        a = analyse_terrain(_elevation(z, sea_clean=bool(seed % 2)), TerrainConfig(drainage_area_km2=SMALL_KM2),
                            precision="float64")
        assert len(a.links) > 10 and max(link.strahler for link in a.links) >= 2
        assert (a.links, a.parts) == _links_as_written(a.core, SMALL_KM2)


def test_link_vertices_are_kept_where_the_line_turns_or_changes_how_it_was_routed():
    """Prevents a line simplified past what lineament work needs: a vertex
    dropped where the line turns or where it passes between a stretch
    routed by slope and one routed across a flat, or a vertex kept where
    nothing changes, which would make straight flat-routed runs look like
    many short segments. Nothing between two vertices is lost."""
    path = [(2, 1), (2, 2), (2, 3), (2, 4), (3, 5), (4, 6), (4, 7), (4, 8), (4, 9), (4, 10)]
    to_sea = [(7, 2), (7, 3), (7, 4), (6, 5), (6, 6)]
    core = _drawn(9, 11, [path, to_sea], sea=[(6, 6)], flat=[(2, 3), (2, 4), (3, 5), (4, 6)], raised=[(2, 4)])
    links, parts = drainage_links(core, ONE_CELL_KM2)
    edge, sea = sorted(links, key=lambda link: link.outlet)
    assert edge.outlet == "edge" and sea.outlet == "sea"
    # E, E, then flat-routed E, NE, NE, E, then by slope again E, E, E.
    assert edge.vertices == ((2, 1), (2, 3), (2, 4), (4, 6), (4, 7), (4, 10))
    assert edge.cells == 10 and edge.flat_routed_cells == 4 and edge.filled_cells == 1
    dx, dg = core.dx, core.dg
    assert edge.length_m == ((((((((dx[2] + dx[2]) + dx[2]) + dg[2]) + dg[3]) + dx[4]) + dx[4]) + dx[4]) + dx[4])
    # A line into the sea ends on the sea cell, and the step into it counts.
    assert sea.vertices == ((7, 2), (7, 4), (6, 5), (6, 6)) and sea.cells == 4
    assert sea.length_m == ((dx[7] + dx[7]) + dg[7]) + dx[6]
    assert sea.area_units == core.area_units[6, 5]
    whole = {part.id: part for part in parts}
    assert whole[edge.id].vertices == edge.vertices
    assert whole[edge.id].stretch_flat == (False, True, True, True, False)
    assert whole[sea.id].stretch_flat == (False, False, False)
    # On random grids: from each vertex the cells run straight along its
    # direction, routed the same way, to the next vertex; and a vertex
    # between the ends is a cell where the direction or the routing changes.
    for seed, rows, cols, step, relief, voids in RANDOM_GRIDS:
        a = analyse_terrain(_elevation(_random_heights(seed, rows, cols, step, relief, voids)),
                            TerrainConfig(drainage_area_km2=SMALL_KM2), precision="float64")
        code, flat = a.core.code, a.core.flat_routed
        upstream: dict[int, list[int]] = {}
        for i, d in enumerate(_downstream(code, a.core.cls)):
            if d >= 0 and a.stream.flat[i]:
                upstream.setdefault(d, []).append(i)
        for line in (*a.links, *a.parts):
            for v, (here, there) in enumerate(zip(line.vertices, line.vertices[1:], strict=False)):
                if isinstance(line, DrainagePart):
                    assert line.stretch_flat[v] == flat[here]
                k = ESRI.index(code[here])
                r, c = here
                while (r, c) != there:
                    assert code[r, c] == code[here] and flat[r, c] == flat[here], "a vertex was dropped"
                    r, c = r + DR[k], c + DC[k]
            for r, c in line.vertices[1:-1]:
                came_from = upstream[r * a.core.cols + c]
                assert len(came_from) == 1
                before = divmod(came_from[0], a.core.cols)
                assert (code[before], flat[before]) != (code[r, c], flat[r, c]), "a vertex where nothing changes"


def test_links_are_cut_where_they_leave_the_shown_square():
    """Prevents lines drawn into the margin, which is analysed only so that
    the edge does not bend the lines, a piece of one cell drawn as a dot, a
    line that leaves and re-enters drawn as one piece across the gap, and a
    piece ending at the edge of the map claiming the line's own outlet."""
    shown = (2, 9, 2, 9)
    path = [(5, 0), (5, 1), (5, 2), (5, 3), (5, 4), (6, 4), (7, 4), (8, 4), (9, 4), (9, 5), (8, 5), (7, 5),
            (7, 6), (7, 7), (7, 8), (7, 9), (7, 10)]
    corner = [(1, 1), (2, 2), (1, 3), (1, 4), (1, 5), (1, 6), (1, 7), (1, 8), (1, 9), (1, 10)]
    core = _drawn(12, 11, [path, corner], shown=shown)
    links, parts = drainage_links(core, ONE_CELL_KM2)
    grazing, crossing = links
    assert grazing.vertices[0] == (1, 1) and crossing.vertices[0] == (5, 0)
    assert all(part.id == crossing.id for part in parts), "a piece of one cell was kept"
    first, second = parts
    dx, dy = core.dx, core.dy
    assert (first.part, second.part) == (0, 1)
    assert first.vertices == ((5, 2), (5, 4), (8, 4)) and first.outlet == "beyond_view"
    assert first.length_m == (((dx[5] + dx[5]) + dy[5]) + dy[6]) + dy[7]
    assert first.area_units == core.area_units[8, 4] and first.strahler == crossing.strahler == 1
    assert second.vertices == ((8, 5), (7, 5), (7, 8)) and second.outlet == "beyond_view"
    assert second.length_m == ((dy[8] + dx[7]) + dx[7]) + dx[7]
    assert second.area_units == core.area_units[7, 8] and crossing.area_units == core.area_units[7, 10]
    assert crossing.outlet == "edge" and crossing.vertices[-1] == (7, 10)
    # A square holding the line's end gives the piece the line's outlet;
    # over the whole grid each line is one piece, the same as the line.
    wider = dataclasses.replace(core, shown=(2, 9, 2, 11))
    assert drainage_links(wider, ONE_CELL_KM2)[1][-1].outlet == "edge"
    everything = dataclasses.replace(core, shown=(0, 12, 0, 11))
    for link, part in zip(*drainage_links(everything, ONE_CELL_KM2), strict=True):
        assert (part.id, part.part, part.vertices, part.outlet, part.length_m, part.area_units) == (
            link.id, 0, link.vertices, link.outlet, link.length_m, link.area_units)
    # Against the rules written out, on random grids and random squares.
    rng = np.random.default_rng(41)
    cut = 0
    for seed, rows, cols, step, relief, voids in RANDOM_GRIDS:
        r0, c0 = int(rng.integers(0, rows // 3)), int(rng.integers(0, cols // 3))
        r1, c1 = int(rng.integers(rows // 2, rows + 1)), int(rng.integers(cols // 2, cols + 1))
        a = analyse_terrain(_elevation(_random_heights(seed, rows, cols, step, relief, voids)),
                            TerrainConfig(drainage_area_km2=SMALL_KM2), shown=(r0, r1, c0, c1), precision="float64")
        assert a.parts == _links_as_written(a.core, SMALL_KM2)[1]
        cut += sum(part.outlet == "beyond_view" for part in a.parts)
        for part in a.parts:
            assert all(r0 <= r < r1 and c0 <= c < c1 for r, c in part.vertices) and len(part.vertices) >= 2
        assert [(p.id, p.part) for p in a.parts] == sorted((p.id, p.part) for p in a.parts)
    assert cut > 10


def test_the_vertices_of_a_piece_are_found_by_binary_search_as_the_rule_writes_them():
    """Prevents the binary search over a line's turns, which spares a line
    cut into many pieces a scan of every turn for each piece, from keeping
    other vertices than spec 3.10's rule: both ends, and every turn
    strictly between them. Held on random sorted turn lists, with turns at
    either end of the piece, none at all, and pieces of one and two
    positions."""
    from groundwater.mapping.terrain_analysis import _vertex_positions

    def written(turns, a, b):
        return [a] if b - a == 1 else [a] + [m for m in turns if a < m < b - 1] + [b - 1]

    rng = np.random.default_rng(41_15)
    cases = [([], 0, 1), ([], 3, 5), ([1, 2, 3], 0, 2), ([4], 4, 6), ([5], 4, 6), ([4, 5, 6], 4, 7)]
    for _ in range(3000):
        turns = sorted({int(m) for m in rng.integers(1, 60, int(rng.integers(0, 30)))})
        a = int(rng.integers(0, 58))
        b = a + int(rng.integers(1, 12))
        if turns and rng.random() < 0.3:
            a = int(rng.choice(turns))
            b = a + int(rng.integers(1, 12))
        if turns and rng.random() < 0.3:
            b = int(rng.choice(turns)) + 1
            a = max(0, b - int(rng.integers(1, 12)))
        cases.append((turns, a, b))
    for turns, a, b in cases:
        assert _vertex_positions(turns, a, b) == written(turns, a, b), (turns, a, b)


#: A threshold of about two and a half cells at 8.5 degrees north: above
#: what a wall of _serpentine gathers, below what its channel's head does.
SERPENTINE_KM2 = 0.0025


def _serpentine(rows: int = 121, cols: int = 120) -> tuple[np.ndarray, list[tuple[int, int]], set]:
    """One channel that turns at every cell, and where it runs: it zigzags
    between the two rows of each three-row lane, the lanes running east and
    west in turn and joined through the wall row between them (the joins,
    returned too, are the only cells where it runs on without turning), and
    it leaves the grid at the west or east edge. The channel falls a
    centimetre a cell; every other cell is a wall 2,000 m high that drains
    straight into it. Each lane crosses the square a margin of 20 cells
    leaves, so the one line is cut into dozens of pieces of dozens of
    vertices each."""
    path: list[tuple[int, int]] = []
    joins = set()
    r, east = 1, True
    while r + 2 < rows:
        columns = range(1, cols - 1) if east else range(cols - 2, 0, -1)
        path += [(r + k % 2, c) for k, c in enumerate(columns)]
        if r + 5 < rows:
            path.append((r + 2, path[-1][1]))        # through the wall to the next lane
            joins.add(path[-1])
        r, east = r + 3, not east
    path.append((path[-1][0], cols - 1 if not east else 0))
    z = np.full((rows, cols), 2000.0)
    for p, cell in enumerate(path):
        z[cell] = 1000.0 + (len(path) - p) / 100.0
    # the channel takes no short cut: no cell of it touches one further on
    # than the next
    at = {cell: p for p, cell in enumerate(path)}
    for p, (pr, pc) in enumerate(path):
        assert all(at.get((pr + dr, pc + dc), p + 1) <= p + 1 for dr in (-1, 0, 1) for dc in (-1, 0, 1))
    return z, path, joins


def test_a_line_cut_into_many_pieces_keeps_every_vertex_of_each():
    """One line that turns at every cell and crosses the edge of the square
    shown again and again (a hostile upload of this shape once spent eight
    of its nine seconds of tracing rescanning the line's turns for each
    piece): every piece is the rule written out cell by cell, and, as the
    line turns at every cell, every position of a piece is a vertex.
    Prevents a vertex lost or doubled at the ends of a piece, where the
    binary search's bounds fall."""
    z, path, joins = _serpentine()
    rows, cols = z.shape
    a = analyse_terrain(_elevation(z), TerrainConfig(drainage_area_km2=SERPENTINE_KM2),
                        shown=(20, rows - 20, 20, cols - 20), precision="float64")
    assert len(a.links) == 1 and a.links[0].cells == len(path) and a.links[0].outlet == "edge"
    assert a.links[0].vertices == tuple(cell for cell in path if cell not in joins)
    assert len(a.parts) > 20 and min(len(part.vertices) for part in a.parts) > 30
    assert (a.links, a.parts) == _links_as_written(a.core, SERPENTINE_KM2)
    for part in a.parts:
        first = path.index(part.vertices[0])
        assert part.vertices == tuple(path[first:first + len(part.vertices)])


def test_the_shown_links_do_not_change_when_the_margin_grows():
    """Prevents the lines shown from depending on how far beyond the map the
    analysis reached, once the margin holds every divide: on a corrugated
    surface of short gullies running down to sea channels, with a level
    terrace and a hollow, margins of 16 and 32 cells give the same pieces
    to the bit, while no margin at all does not."""
    step, shown, big = 2.0 ** -12, 40, 32        # a lattice whose coordinates are exact in binary
    n = shown + 2 * big
    r = np.arange(n)[:, None]
    c = np.arange(n)[None, :]
    strip = r % 12
    z = np.minimum(strip, 12 - strip) * 2.0 + np.abs((c % 8) - 4) * 0.75 + 0.25 * ((r * 7 + c * 13) % 5)
    z = np.where(strip == 0, -1.0, z)           # sea channels every 12 rows, joined to the west and east edges
    z[40:46, 42:55] = 5.0                       # a level valley floor across three gullies
    z[63, 50] -= 6.0                            # a hollow filled by more than a metre
    cfg = TerrainConfig(drainage_area_km2=0.004)

    def shown_lines(margin: int):
        o, size = big - margin, shown + 2 * margin
        grid = ElevationGrid(-12.0 + (o + np.arange(size)) * step, 8.0 + (o + np.arange(size)) * step,
                             z[o:o + size, o:o + size].copy(), sea_clean=True)
        a = analyse_terrain(grid, cfg, shown=(margin, margin + shown, margin, margin + shown), precision="float64")
        first = {link.id: divmod(link.start, a.core.cols) for link in a.links}

        def moved(cell):
            return cell[0] - margin, cell[1] - margin

        # ids count the lines in the margin too, so a line is named by the
        # cell it starts at, counted from the square shown
        return [(moved(first[part.id]), dataclasses.replace(
                    part, id=0, vertices=tuple(map(moved, part.vertices)),
                    downstream=0 if part.downstream < 0 else 1),
                 moved(first[part.downstream]) if part.downstream >= 0 else None)
                for part in a.parts], a.summary

    sixteen, summary = shown_lines(16)
    assert len(sixteen) > 100 and {p.outlet for _, p, _ in sixteen} >= {"sea", "confluence", "beyond_view"}
    assert summary["raised"] > 0 and summary["flat_routed_stream"] > 10
    assert max(p.strahler for _, p, _ in sixteen) == 3
    assert shown_lines(32) == (sixteen, summary)
    assert shown_lines(0)[0] != sixteen


def test_drainage_links_from_the_core_equal_those_of_the_full_analysis():
    """Prevents the browser's re-threshold on the page, which traces the
    lines again from the core its worker handed over, from drawing other
    lines than a full analysis at that threshold: the core is all the
    tracing needs, whether its counts arrive as int64 or, as the browser
    holds them, as float64."""
    z = _random_heights(4, 50, 45, 1.0, 3.0, 0.02)
    cfg = TerrainConfig(drainage_area_km2=SMALL_KM2)
    shown = (6, 44, 5, 40)
    a = analyse_terrain(_elevation(z, sea_clean=False), cfg, shown=shown)
    assert drainage_links(a.core, SMALL_KM2) == (a.links, a.parts) and len(a.parts) > 10
    handed = dataclasses.replace(a.core, count=a.core.count.astype(np.float64),
                                 area_units=a.core.area_units.astype(np.float64))
    assert drainage_links(handed, SMALL_KM2) == (a.links, a.parts)
    for area in (0.001, 0.01):
        b = analyse_terrain(_elevation(z, sea_clean=False), dataclasses.replace(cfg, drainage_area_km2=area),
                            shown=shown)
        assert drainage_links(a.core, area) == (b.links, b.parts)
        meta = _meta(a.core, area=area)
        assert drainage_geojson(a.core, drainage_links(handed, area)[1], meta) == \
            drainage_geojson(b.core, b.parts, meta)
    with pytest.raises(ValueError):
        drainage_links(a.core, math.nan)


def test_a_drainage_area_too_large_to_count_in_units_is_refused():
    """Prevents an OverflowError from Python where the browser answered with
    no lines: an area past about 1.8e300 km² counts to infinity in 0.01 m²
    units, which has no whole number to floor to, so both engines refuse it
    with the sentence they give any area that is not a number of square
    kilometres. The largest area that still counts is taken, and gives no
    lines."""
    core = _drawn(4, 5, [[(1, 0), (1, 1), (1, 2), (1, 3), (1, 4)]])
    for area in (1.8e300, 1e301, sys.float_info.max):
        with pytest.raises(ValueError, match="^the drainage area must be a number of square kilometres, not "):
            drainage_links(core, area)
        with pytest.raises(ValueError, match=re.escape(repr(area))):
            analyse_terrain(_elevation(np.arange(20.0).reshape(4, 5)), TerrainConfig(drainage_area_km2=area))
    assert drainage_links(core, 1.7976931348623156e300) == ((), ())
    assert len(drainage_links(core, ONE_CELL_KM2)[0]) == 1


def test_the_hillshade_panels_need_an_azimuth_to_name():
    """Prevents an IndexError from deep inside and_join where the browser
    refuses in words: captions for an analysis whose panel list is empty
    are refused with the browser's sentence, word for word."""
    a = analyse_terrain(_elevation(np.add.outer(np.arange(12.0), np.arange(10.0))),
                        TerrainConfig(hillshade_panel_azimuths_deg=()), precision="float64")
    assert a.hillshades == ()
    with pytest.raises(ValueError, match="^the hillshade panels need at least one azimuth$"):
        terrain_captions(a, None, "here")


def test_the_drainage_geojson_escapes_names_and_rounds_as_python_does():
    """Prevents the two engines writing different bytes for the same lines:
    a file or place name with quotes, a backslash, control characters or
    letters outside ASCII is escaped as Python's json.dumps escapes it with
    ensure_ascii, and every number is written in its fixed form, rounded
    from its binary value as Python rounds it (-0.000000 for a small
    negative), with no whitespace anywhere outside the strings."""
    z = _random_heights(2, 41, 37, 0.1, 2.0, 0.0)
    rows, cols = z.shape
    grid = ElevationGrid(-4e-7 + np.arange(cols) / 3600, 8.4999995 + np.arange(rows) / 3600, z, sea_clean=True)
    a = analyse_terrain(grid, TerrainConfig(drainage_area_km2=SMALL_KM2), shown=(5, 36, 4, 33))
    name = 'Bo "east" \\ tile\n\t\x01 Mɔyamba – Sɛwa \U0001f30a \x7f'
    meta = _meta(a.core, label=name, credit="© \"x\"", centre=WindowCentre(-4e-7, 8.4999995, name, False))
    text = drainage_geojson(a.core, a.parts, meta)
    assert text.isascii() and not re.search(r"\s", re.sub(r'"(?:[^"\\]|\\.)*"', "", text))
    for escaped in ('\\"east\\"', "\\\\ tile", "\\n", "\\t", "\\u0001", "M\\u0254yamba", "\\u2013",
                    "\\ud83c\\udf0a", "\\u007f", "\\u00a9", "km\\u00b2"):
        assert escaped in text, escaped
    description = phrase("terrain.geojson_description", label=name, area=SMALL_KM2, radius=1.0, where=name,
                         margin=0.5, surface=meta["surface"])
    assert json.dumps(description) in text
    doc = _parsed(text)
    assert doc["description"] == description and doc["attribution"] == "© \"x\""
    assert doc["centre"] == ["-0.000000", f"{8.4999995:.6f}"]
    assert (doc["drainage_area_km2"], doc["radius_km"], doc["margin_km"]) == ("0.003", "1", "0.5")
    assert len(doc["features"]) == len(a.parts) > 10
    for feature, part in zip(doc["features"], a.parts, strict=True):
        props = feature["properties"]
        assert props["area_km2"] == f"{part.area_units / 1e8:.6f}"
        assert props["length_m"] == f"{part.length_m:.1f}"
        assert (props["id"], props["part"], props["strahler"], props["downstream"]) == (
            str(part.id), str(part.part), str(part.strahler), str(part.downstream))
        assert feature["geometry"]["coordinates"] == [
            [f"{grid.lons[c]:.6f}", f"{grid.lats[r]:.6f}"] for r, c in part.vertices]
        assert re.fullmatch(r"\d+\.\d{6}", props["area_km2"]) and re.fullmatch(r"\d+\.\d", props["length_m"])


def test_the_drainage_geojson_carries_its_description_threshold_and_window():
    """Prevents a download of drainage lines that, once separated from the
    app, no longer says what they are: candidates worked out from which
    model at which threshold, over which window and margin, credited as the
    licence asks, with the Copernicus liability sentence when (and only
    when) the set holds a Copernicus file."""
    read = read_elevation([(name, DEM / name) for name in COPERNICUS_PAIR], None, 0.4, margin_km=0.2)
    cfg = TerrainConfig(drainage_area_km2=0.01)
    a = analyse_terrain(read.grid, cfg, assumed_sea=read.assumed_sea, shown=read.shown)
    meta = {"label": read.grid.source, "credit": read.grid.credit, "notice": read.notice, "surface": read.surface,
            "area": 0.01, "radius": 0.4, "margin": 0.2, "centre": read.centre}
    doc = json.loads(drainage_geojson(a.core, a.parts, meta))
    assert list(doc) == ["type", "description", "attribution", "notice", "drainage_area_km2", "radius_km",
                         "margin_km", "centre", "features"]
    assert doc["type"] == "FeatureCollection"
    assert doc["description"] == phrase("terrain.geojson_description", label=read.grid.source, area=0.01,
                                        radius=0.4, where=read.centre.label, margin=0.2, surface=read.surface)
    assert doc["description"] == terrain_captions(a, read, read.centre.label)["geojson_description"]
    assert "Copernicus GLO-30 tiles N08 W012 and N08 W011" in doc["description"]
    assert doc["attribution"] == phrase("terrain.credit_copernicus_modified")
    assert doc["notice"] == phrase("terrain.copernicus_liability")
    assert (doc["drainage_area_km2"], doc["radius_km"], doc["margin_km"]) == (0.01, 0.4, 0.2)
    assert doc["centre"] == [float(f"{read.centre.lon:.6f}"), float(f"{read.centre.lat:.6f}")]
    assert len(doc["features"]) == len(a.parts) > 0
    for feature, part in zip(doc["features"], a.parts, strict=True):
        assert list(feature) == ["type", "properties", "geometry"]
        assert feature["type"] == "Feature" and feature["geometry"]["type"] == "LineString"
        assert list(feature["properties"]) == ["id", "part", "strahler", "outlet", "area_km2", "length_m",
                                               "edge_contaminated", "filled_cells", "flat_routed_cells",
                                               "downstream"]
        props = feature["properties"]
        assert (props["id"], props["part"], props["outlet"], props["edge_contaminated"], props["filled_cells"],
                props["flat_routed_cells"]) == (part.id, part.part, part.outlet, part.edge_contaminated,
                                                part.filled_cells, part.flat_routed_cells)
    # Without a Copernicus file there is no notice member at all.
    plain = json.loads(drainage_geojson(a.core, a.parts, dict(meta, notice=None, credit="")))
    assert "notice" not in plain and plain["attribution"] == ""
    assert json.loads(drainage_geojson(a.core, (), meta))["features"] == []


def test_thresholds_are_taken_in_float64_before_storage_narrows():
    """Prevents a verdict taken on a float32 copy: a hollow filled by just
    under a metre is 1.0 m once stored in float32, but it is not raised,
    its depth is reported to the last bit, and every count, share and
    display limit of the summary is the same whichever storage was asked
    for."""
    short = 1.0 - 2.0 ** -26                     # float32 rounds it to exactly 1.0
    assert np.float32(short) == 1.0
    z = np.full((10, 12), 10.0)
    z[2:4, 2:4] = 10.0 - short                   # filled by just under a metre
    z[2:4, 7:9] = 9.0                            # filled by a metre exactly
    z[6:8, 4:6] = 10.0 - 2.0 ** -20
    cfg = TerrainConfig(drainage_area_km2=SMALL_KM2)
    narrow = analyse_terrain(_elevation(z), cfg)
    wide = analyse_terrain(_elevation(z), cfg, precision="float64")
    for a in (narrow, wide):
        assert not a.core.raised[2:4, 2:4].any() and a.core.raised[2:4, 7:9].all()
        assert a.core.raised.sum() == 4 and a.summary["raised"] == 4
        assert a.core.flat_routed[2:4, 2:4].all() and a.core.flat_routed[6:8, 4:6].all()
    assert narrow.fill_depth.dtype == np.float32 and (narrow.fill_depth[2:4, 2:4] == 1.0).all()
    assert (wide.fill_depth[2:4, 2:4] == short).all()
    assert narrow.summary == wide.summary
    assert (narrow.links, narrow.parts) == (wide.links, wide.parts)
    only = z.copy()
    only[2:4, 7:9] = 10.0
    assert analyse_terrain(_elevation(only), cfg).summary["max_fill_m"] == short
    # The display limits too: the wetness range is chosen on the exact
    # argument and curvature's on the float64 layers.
    hilly = _random_heights(9, 40, 40, 1.0, 3.0, 0.02) * 10.0
    narrow = analyse_terrain(_elevation(hilly), cfg)
    wide = analyse_terrain(_elevation(hilly), cfg, precision="float64")
    assert narrow.summary == wide.summary
    low, high = display_range(wide.twi_arg, 0.02, 0.98)
    assert narrow.summary["twi_range"] == (float(np.log(low)), float(np.log(high)))
    bends = np.abs(np.concatenate([wide.profile.ravel(), wide.tangential.ravel()]))
    assert narrow.summary["curvature_limit"] == display_range(bends, 0.98, 0.98)[0] > 0


def test_float32_storage_rounds_the_float64_kernels():
    """Prevents the float32 layers from being anything but the float64
    kernels rounded once (a kernel run in float32 would draw other
    shading), and the layers held for parity and lineament work - p, q,
    the wetness argument, the filled surface and the core - from being
    narrowed at all."""
    z = _random_heights(5, 33, 33, 0.1, 1.0, 0.08) * 40.0
    assumed = np.zeros(z.shape, dtype=bool)
    assumed[:6, -5:] = True
    cfg = TerrainConfig(drainage_area_km2=SMALL_KM2)
    wide = analyse_terrain(_elevation(z), cfg, assumed_sea=assumed, precision="float64")
    narrow = analyse_terrain(_elevation(z), cfg, assumed_sea=assumed, precision="float32")
    pairs = [(getattr(wide, name), getattr(narrow, name))
             for name in ("tanb", "hillshade_multi", "twi", "profile", "tangential", "fill_depth")]
    pairs += list(zip(wide.hillshades, narrow.hillshades, strict=True))
    assert len(narrow.hillshades) == len(cfg.hillshade_panel_azimuths_deg) == 4
    for x64, x32 in pairs:
        assert x64.dtype == np.float64 and x32.dtype == np.float32
        assert x32.tobytes() == x64.astype(np.float32).tobytes()
        assert np.isfinite(x64).any() and np.isnan(x64).any()
    for name in ("p", "q", "twi_arg", "filled", "stream"):
        assert getattr(narrow, name).tobytes() == getattr(wide, name).tobytes(), name
    assert narrow.p.dtype == narrow.q.dtype == narrow.twi_arg.dtype == narrow.filled.dtype == np.float64
    for f in dataclasses.fields(TerrainCore):
        x, y = getattr(narrow.core, f.name), getattr(wide.core, f.name)
        assert (x.tobytes() == y.tobytes()) if isinstance(x, np.ndarray) else x == y, f.name
    with pytest.raises(ValueError):
        analyse_terrain(_elevation(z), cfg, precision="float16")


def test_every_caption_names_its_figure_and_the_caveat_is_the_catalogued_one():
    """Prevents a figure printed with another figure's caption, a caption
    that leaves out what the figure cannot be trusted for (the sea, a
    zero-filled gap, sea in a file of unstated source, a flat left without
    a direction) or mentions one the square does not show, and a caveat or
    a GeoJSON description in words other than the catalogue's. (That the
    caveat is drawn inside each figure is for the figures' own test.)"""
    read = read_elevation([(name, DEM / name) for name in COPERNICUS_PAIR], None, 0.4, margin_km=0.2)
    cfg = TerrainConfig(drainage_area_km2=0.01)
    a = analyse_terrain(read.grid, cfg, assumed_sea=read.assumed_sea, shown=read.shown)
    caps = terrain_captions(a, read, "Kakua")
    s = a.summary
    assert read.surface == phrase("terrain.surface_copernicus")
    titles = {"title_relief": "Shaded relief and drainage lines - Kakua",
              "title_wetness": "Topographic wetness index - Kakua", "title_curvature": "Curvature - Kakua",
              "title_directions": "Shaded relief from four directions - Kakua"}
    assert {key: caps[key] for key in titles} == titles
    assert [caps[f"panel_{n}"] for n in range(4)] == [
        "Light from 270°", "Light from 315°", "Light from 0°", "Light from 45°"]
    candidates = phrase("terrain.caption_candidates")
    relief = [phrase("terrain.caption_relief", interval=s["contour_interval"], area=0.01),
              phrase("terrain.caption_fill", lines_pct=s["flat_routed_lines_pct"], pct=s["raised_pct"], depth=1.0),
              phrase("terrain.caption_edge", margin=0.2), candidates]
    assert s["sea_pct"] == s["zero_fill"] == s["unresolved"] == 0
    assert caps["relief"] == " ".join(relief)
    assert caps["wetness"] == " ".join([phrase("terrain.caption_twi", floor=0.001, n=s["floored"]), candidates,
                                        read.surface])
    curvature = re.fullmatch(r"Curvature over (\d+) m, per km\. .*", caps["curvature"])
    assert curvature and abs(int(curvature.group(1)) - cfg.curvature_spacing_m) < 31
    assert caps["curvature"].endswith(f"{candidates} {read.surface}")
    assert caps["directions"] == phrase("terrain.caption_directions", azimuths="270°, 315°, 0° and 45°",
                                        altitude=45.0)
    assert caps["figure_caveat"] == phrase("terrain.figure_caveat", surface=read.surface)
    assert caps["geojson_description"] == phrase("terrain.geojson_description", label=read.grid.source, area=0.01,
                                                 radius=0.4, where="Kakua", margin=0.2, surface=read.surface)
    stages = ("classes", "fill", "flow", "flats", "accumulate", "drainage", "shading", "curvature")
    assert [caps[f"stage_{name}"] for name in stages] == [phrase(f"terrain.stage_{name}") for name in stages]
    heard = []
    analyse_terrain(read.grid, cfg, assumed_sea=read.assumed_sea, shown=read.shown,
                    progress=lambda fraction, label: heard.append((fraction, label)))
    assert [label for _, label in heard[:-1]] == [caps[f"stage_{name}"] for name in stages]
    assert [fraction for fraction, _ in heard] == sorted(fraction for fraction, _ in heard)
    assert heard[0][0] == 0.0 and heard[-1][0] == 1.0

    # Sea, a zero-filled gap and a file of unstated source, read whole.
    rows, cols = 24, 30
    z = 3.0 + np.arange(rows)[:, None] * 0.4 + np.abs((np.arange(cols)[None, :] % 6) - 3) * 0.2
    z = z + np.zeros((rows, cols))
    for c, depth in enumerate([2, 3, 1, 2, 3, 2, 1, 3, 2]):
        z[:depth, c] = -1.0                      # a ragged sea in the south-west
    z[:, 24:] = 0.0                              # a gap a mosaic filled with 0 m, with a straight edge
    gappy = dataclasses.replace(cfg, sea_straight_edge_cells=12, drainage_area_km2=SMALL_KM2)
    b = analyse_terrain(_elevation(z, sea_clean=False), gappy)
    caps = terrain_captions(b, None, "Kakua")
    s = b.summary
    assert s["sea"] > 0 and s["zero_fill"] == rows * 6 and s["unresolved"] == 0
    assert s["land"] + s["sea"] + s["assumed_sea"] + s["uncovered"] + s["zero_fill"] == s["cells"] == z.size
    assert s["zero_fill_pct"] == (100.0 * rows * 6) / z.size and s["sea_pct"] == (100.0 * s["sea"]) / z.size
    surface = phrase("terrain.surface_unknown")
    relief = [phrase("terrain.caption_relief", interval=s["contour_interval"], area=SMALL_KM2),
              phrase("terrain.caption_fill", lines_pct=s["flat_routed_lines_pct"], pct=s["raised_pct"], depth=1.0),
              phrase("terrain.caption_edge", margin=gappy.analysis_buffer_km),
              phrase("terrain.caption_sea", pct=s["sea_pct"], level=0.0),
              phrase("terrain.caption_sea_unstated", level=0.0),
              phrase("terrain.caption_zero_fill", pct=s["zero_fill_pct"], level=0.0)]
    assert caps["relief"] == " ".join([*relief, candidates])
    assert caps["figure_caveat"] == phrase("terrain.figure_caveat", surface=surface)
    assert caps["wetness"].endswith(surface) and caps["curvature"].endswith(surface)
    unresolved = dataclasses.replace(b, summary={**s, "unresolved": 3})
    assert terrain_captions(unresolved, None, "Kakua")["relief"] == " ".join(
        [*relief, phrase("terrain.caption_unresolved", n=3), candidates])
    clean = analyse_terrain(_elevation(z, sea_clean=True, source_id="srtm"), gappy)
    caps = terrain_captions(clean, None, "Kakua")
    assert phrase("terrain.caption_sea_unstated", level=0.0) not in caps["relief"]
    assert caps["figure_caveat"] == phrase("terrain.figure_caveat", surface=phrase("terrain.surface_srtm"))


def test_the_analysis_is_a_function_of_the_window_alone():
    """Prevents an analysis that depends on anything but the window - its
    heights and cells, the assumed sea, the square shown, the settings and
    the source's sea rule - such as the label or the files it was read
    from, the memory layout of its heights, a negative zero, a cache or
    state left by an earlier run, or one that changes what it was given."""
    z = _random_heights(4, 50, 45, 1.0, 3.0, 0.02)
    z[z == 0] = -0.0
    z[20, 20] = np.inf                           # a height no reader would pass on
    assumed = np.zeros(z.shape, dtype=bool)
    assumed[:12, :8] = True
    shown = (6, 44, 5, 40)
    cfg = TerrainConfig(drainage_area_km2=SMALL_KM2)
    given = (z.copy(), assumed.copy())
    first = analyse_terrain(_elevation(z, source="one", files=("a.tif",), credit="x"), cfg,
                            assumed_sea=assumed, shown=shown)
    assert z.tobytes() == given[0].tobytes() and assumed.tobytes() == given[1].tobytes()
    positive = np.asfortranarray(np.where(z == 0, 0.0, z))
    other = analyse_terrain(_elevation(positive, source="two", files=("b.hgt", "c.hgt"),
                                       resolution_note="about 31 by 31 m", source_id="hgt"), cfg,
                            assumed_sea=assumed.astype(np.uint8), shown=list(shown))
    again = analyse_terrain(_elevation(z), cfg, assumed_sea=assumed, shown=shown)
    assert _fingerprint(first) == _fingerprint(other) == _fingerprint(again)
    # The summary counts each cell of the square shown once.
    s = first.summary
    view = (slice(shown[0], shown[1]), slice(shown[2], shown[3]))
    assert s["assumed_sea"] == assumed[view].sum() > 0 and s["implausible"] == 1
    assert s["voids"] == (np.isnan(z) & ~assumed)[view].sum() > 0
    assert s["uncovered"] == s["voids"] + s["implausible"] and s["zero_fill"] == 0
    assert s["land"] + s["sea"] + s["assumed_sea"] + s["uncovered"] + s["zero_fill"] == s["cells"]
    assert s["cells"] == (shown[1] - shown[0]) * (shown[3] - shown[2])
    # What a model holds beyond the window cannot reach the analysis: the
    # same window cut from a larger model gives the same answer.
    big = np.full((60, 55), 50.0)
    big[3:53, 4:49] = z
    lons, lats = -12.0 + (np.arange(55) - 4) * (1 / 3600), 8.5 + (np.arange(60) - 3) * (1 / 3600)
    cut = ElevationGrid(lons[4:49], lats[3:53], big[3:53, 4:49], sea_clean=True)
    assert _fingerprint(analyse_terrain(cut, cfg, assumed_sea=assumed, shown=shown)) == _fingerprint(first)
    with pytest.raises(ValueError):
        analyse_terrain(_elevation(z), cfg, shown=(0, 51, 0, 45))

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

The grids are south-first, as the analysis holds them: row 0 is the south
edge and north is row + 1.
"""

from __future__ import annotations

import hashlib
import heapq
import inspect
import subprocess
import sys
from collections import deque
from types import SimpleNamespace

import numpy as np
import pytest

from groundwater.config import TerrainConfig
from groundwater.mapping import terrain_analysis as ta
from groundwater.mapping.elevation import RowMetric, row_metric
from groundwater.mapping.terrain_analysis import (
    LAND,
    SEA,
    VOID,
    accumulate_flow,
    classify_cells,
    fill_depressions,
    flow_directions,
    resolve_flats,
)

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
    insertion), a first-in first-out queue for cells raised into a pit."""
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
    # Where the surface kernels are merged: no slope is computed beside
    # assumed sea, because its 3 by 3 window holds no height there.
    horn = getattr(ta, "horn_gradients", None)
    if horn is not None:
        p, q, tanb = horn(out.zt, out.metric)
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

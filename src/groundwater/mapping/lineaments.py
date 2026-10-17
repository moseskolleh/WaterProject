"""Lineament candidates: straight valleys and ridges in the terrain, found
in the shading (PLAN.md step 4.2).

In crystalline basement, most of Sierra Leone, a borehole finds water where
it meets a fracture zone, and a fracture zone often shows on the surface as
a straight valley, a straight ridge or a line of valleys that line up. This
module finds such straight features in a window that
:func:`.terrain_analysis.analyse_terrain` has analysed, and draws their
strikes as a rose. They are candidates: inferred from terrain, not
confirmed by geophysics, and a road, a field boundary or a geological
contact draws a straight line too.

The method, in the order :func:`lineament_candidates` runs it:

* The heights are smoothed with binomial passes, about
  ``lineament_smoothing_m`` across. Unsmoothed, the tree canopy that a
  surface model records breaks every edge into pieces of a few cells.
* The smoothed relief is shaded from the panel azimuths (270, 315, 0 and 45
  degrees), and the gradients of the four hillshades are added up as a
  structure tensor. One hillshade finds an edge best when it is lit across
  it, so edges taken from each hillshade alone come out bunched round the
  four strikes across the panels' light: on random terrain with no
  preferred direction the rose of such edges showed a 90-degree pattern of
  amplitude 0.10, about five standard errors. To first order the gradient
  of a hillshade is the Hessian of the heights applied to the direction of
  the sun, and four suns 45 degrees apart add up to twice the Hessian's
  square whatever the strike, so the tensor's strength favours no
  direction, and its principal direction runs across the line.
* A cell whose ground bends across the line by less than
  ``lineament_min_curvature_per_km`` is on no line, however it compares
  with its surroundings.
* Cells where that strength peaks across the line are its centreline:
  Canny's thinning, with the strength on each side read between the two
  neighbouring cells the direction falls between. Each centreline cell is
  weighed against the mean strength around it, ``lineament_contrast_km``
  across, so that a shallow valley on the plains counts as well as a deep
  one in the hills, and the strongest ``lineament_share`` of the centreline
  cells of the square shown are kept. A cell is a valley or a ridge by the
  sign of the curvature across the line.
* Neighbouring centreline cells of one kind whose directions differ by no
  more than ``lineament_turn_deg`` make one line. Each line is cut into
  straight pieces at the cell furthest from its axis until none lies more
  than ``lineament_straight_m`` from it; a cell that strays near an end, a
  spur, is dropped instead, so that it does not cut a straight line short.
* Pieces of one kind that lie along one line, with a gap of no more than
  ``lineament_link_gap_m``, are linked into one candidate: this is how
  aligned valleys become one lineament. Candidates at least
  ``lineament_min_length_m`` long within the square shown are kept, cut to
  it.

Valleys are not traced from the drainage lines. A drainage line follows
single-neighbour (D8) routing, which can only step along the grid's rows,
columns and diagonals: on random terrain the straight runs of its lines
showed rose patterns of amplitude 0.55 to 0.59, ten to twenty standard
errors, all from the grid. Here a valley is a line of the terrain itself.

Everything is worked out in the window's own frame: metres east and north
from the window's first cell, at the cell size of the middle row of the
square shown (a tile's cells narrow by 0.26% across it, so lengths and
strikes are good to that). Every decision is taken with additions,
multiplications, divisions and square roots in a fixed order, sums of
whole numbers, and sines, cosines and arctangents of polynomials, so that
the browser's engine in ``docs/js/gwt-core.js``, which runs the same steps
in the same order, gives the same candidates to the bit.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np

from ..config import TerrainConfig
from ..text import phrase
from ..utils import and_join
from .elevation import sin_cos_deg
from .terrain_analysis import (
    LAND,
    VOID,
    TerrainAnalysis,
    _json_text,
    display_range,
    hillshade_layer,
    horn_gradients,
)

__all__ = [
    "Lineament",
    "LineamentAnalysis",
    "VALLEY",
    "RIDGE",
    "atan2_deg",
    "binomial_smooth",
    "lineament_candidates",
    "lineament_captions",
    "lineament_geojson",
    "lineament_lonlat",
]

#: The kinds of a centreline cell, a piece and a candidate: the ground bends
#: up across a valley and down across a ridge.
VALLEY, RIDGE = 1, -1
_KIND_NAME = {VALLEY: "valley", RIDGE: "ridge"}

#: The rose's bands of strike, each 10 degrees, from 0 to 180.
ROSE_BANDS = 18

#: About how many cells of the grid the centreline is found in at a time.
#: Most of the land can be a line cell, and the thinning holds some twenty
#: arrays over them: taken whole, a window at the cap on cells on the tile
#: N08 W012 raised the peak resident set by 214 MB, and in bands by 90 MB.
_BAND_CELLS = 1 << 17


# --- the arctangent both engines evaluate to the bit
#
# Cephes' atan (Moshier): the argument reduced to 0 .. tan(pi/8) by the
# identities atan(x) = pi/4 + atan((x - 1)/(x + 1)) and pi/2 - atan(1/x),
# then a rational function, every constant written as the shortest decimal
# of the double Cephes' 20-digit one rounds to. math.atan2 and V8's
# Math.atan2 differ in the last bit for some arguments; the strike decides
# the rose's band.

_ATAN_P = (-0.8750608600031904, -16.157537187333652, -75.00855792314705,
           -122.88666844901361, -64.85021904942025)
_ATAN_Q = (24.858464901423062, 165.02700983169885, 432.88106049129027,
           485.3903996359137, 194.5506571482614)
_T3P8 = 2.414213562373095      # tan(3 pi / 8)
_MOREBITS = 6.123233995736766e-17
_PIO2 = 1.5707963267948966
_PIO4 = 0.7853981633974483
_R2D = 180.0 / math.pi


def _atan_nonnegative(x: float) -> float:
    """atan(x) for 0 <= x, in radians."""
    if x > _T3P8:
        y, x, extra = _PIO2, -1.0 / x, _MOREBITS
    elif x <= 0.66:
        y, extra = 0.0, 0.0
    else:
        y, x, extra = _PIO4, (x - 1.0) / (x + 1.0), 0.5 * _MOREBITS
    z = x * x
    num = _ATAN_P[0]
    for k in range(1, 5):
        num = num * z + _ATAN_P[k]
    den = z + _ATAN_Q[0]
    for k in range(1, 5):
        den = den * z + _ATAN_Q[k]
    z = z * num / den
    z = x * z + x
    return y + (z + extra)


def atan2_deg(y: float, x: float) -> float:
    """The angle of the point ``(x, y)`` from the positive x axis, in
    degrees from -180 to 180, as ``math.degrees(math.atan2(y, x))`` gives it
    to within a few units in the last place, from operations both engines
    evaluate alike. The origin gives 0."""
    y = float(y)
    x = float(x)
    if not (math.isfinite(x) and math.isfinite(y)):
        return math.nan
    ax, ay = abs(x), abs(y)
    if ax == 0.0 and ay == 0.0:
        return 0.0
    if ay <= ax:
        a = _atan_nonnegative(ay / ax)
    else:
        a = _PIO2 - _atan_nonnegative(ax / ay)
    if x < 0.0:
        a = math.pi - a
    if y < 0.0:
        a = -a
    return a * _R2D


# --- the relief, smoothed and shaded


def binomial_smooth(z, passes: int) -> np.ndarray:
    """``z`` smoothed by ``passes`` passes of the binomial filter 1-2-1, along
    each row and then along each column, which together approach a Gaussian
    of standard deviation sqrt(passes / 2) cells.

    A cell takes a value only when the three it is worked from are finite
    and inside the grid, so a void and the edge each widen by a cell a
    pass, as the shading's own rule leaves them blank rather than drawing a
    cliff. Each pass adds ``(a + 2b) + c`` and multiplies by 0.25, as the
    browser does.
    """
    z = np.asarray(z, dtype=np.float64)
    if z.ndim != 2:
        raise ValueError(f"the heights must be a two-dimensional grid, not an array of shape {z.shape}")
    passes = int(passes)
    if passes < 0:
        raise ValueError(f"the smoothing passes must be 0 or more, not {passes}")
    rows, cols = z.shape
    a = z.copy()
    if passes == 0:
        return a
    b = np.empty_like(a)
    for _ in range(passes):
        b.fill(np.nan)
        if cols >= 3:
            b[:, 1:-1] = ((a[:, :-2] + 2.0 * a[:, 1:-1]) + a[:, 2:]) * 0.25
        a.fill(np.nan)
        if rows >= 3:
            a[1:-1, :] = ((b[:-2, :] + 2.0 * b[1:-1, :]) + b[2:, :]) * 0.25
    return a


def _edge_tensor(zs: np.ndarray, metric, azimuths: Sequence[float], altitude: float,
                 z_factor: float | None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``(txx, tyy, txy)``: the gradients of the hillshades of ``zs`` lit
    from each of ``azimuths``, by Horn's rule on each row's cell size, added
    up as a structure tensor in the order given, from 0."""
    p, q, tanb = horn_gradients(zs, metric)
    del tanb
    txx = np.zeros(zs.shape)
    tyy = np.zeros(zs.shape)
    txy = np.zeros(zs.shape)
    for azimuth in azimuths:
        shade = hillshade_layer(p, q, azimuth, altitude, z_factor)
        gx, gy, tanb = horn_gradients(shade, metric)
        del shade, tanb
        txx += gx * gx
        tyy += gy * gy
        txy += gx * gy
        del gx, gy
    return txx, tyy, txy


# --- what is found


@dataclass(frozen=True)
class Lineament:
    """One lineament candidate, cut to the square shown.

    ``start`` and ``end`` are ``(x, y)``, metres east and north of the
    centre of the analysed window's first cell (row 0, column 0) in the
    window's frame; the line runs from ``start`` northwards, or eastwards
    when it runs due east. ``strike_deg`` is its direction clockwise from
    grid north, from 0 to under 180. ``kind`` is ``"valley"`` or
    ``"ridge"``. ``pieces`` counts the straight pieces linked into it and
    ``cells`` the centreline cells behind them, over the whole candidate,
    the part beyond the square shown included; ``cut`` says the square
    shown cut it.
    """

    id: int
    kind: str
    start: tuple[float, float]
    end: tuple[float, float]
    length_m: float
    strike_deg: float
    pieces: int
    cells: int
    cut: bool


@dataclass(frozen=True, eq=False)
class LineamentAnalysis:
    """The lineament candidates of one analysed window.

    ``lineaments`` are the candidates in the square shown, cut to it, in
    the order they were found (by the length of their longest piece).
    ``rose_valley_m`` and ``rose_ridge_m`` hold their length in each
    10-degree band of strike from 0 (``ROSE_BANDS`` bands), and
    ``rose_valleys`` and ``rose_ridges`` how many fall in each. ``frame``
    is ``(dx, dy)``, the metres a column and a row span in the window's
    frame. ``summary`` counts what each stage found and gives the settings
    it worked them out with; ``settings`` is the configuration.
    """

    lineaments: tuple[Lineament, ...]
    rose_valley_m: tuple[float, ...]
    rose_ridge_m: tuple[float, ...]
    rose_valleys: tuple[int, ...]
    rose_ridges: tuple[int, ...]
    frame: tuple[float, float]
    shown: tuple[int, int, int, int]
    summary: dict = field(repr=False)
    settings: TerrainConfig = field(repr=False)


def _positive(name: str, value) -> float:
    value = float(value)
    if not (math.isfinite(value) and value > 0.0):
        raise ValueError(f"terrain.{name} must be a number above 0")
    return value


def _settings(cfg: TerrainConfig) -> dict:
    """The lineament settings, each refused unless it is a finite number in
    its range."""
    out = {name: _positive(name, getattr(cfg, name)) for name in (
        "lineament_smoothing_m", "lineament_contrast_km", "lineament_min_curvature_per_km",
        "lineament_turn_deg", "lineament_straight_m",
        "lineament_piece_m", "lineament_min_length_m", "lineament_link_angle_deg",
        "lineament_link_offset_m", "lineament_link_gap_m")}
    share = float(cfg.lineament_share)
    if not (math.isfinite(share) and 0.0 < share <= 1.0):
        raise ValueError("terrain.lineament_share must be above 0 and at most 1")
    out["lineament_share"] = share
    for name in ("lineament_turn_deg", "lineament_link_angle_deg"):
        if out[name] >= 90.0:
            raise ValueError(f"terrain.{name} must be under 90 degrees")
    return out


def _empty(cfg: TerrainConfig, shown, frame, summary) -> LineamentAnalysis:
    zeros = (0.0,) * ROSE_BANDS
    none = (0,) * ROSE_BANDS
    return LineamentAnalysis((), zeros, zeros, none, none, frame, shown, summary, cfg)


def _heights(analysis: TerrainAnalysis) -> np.ndarray:
    """The heights the routing worked from: the grid's, with -0 made +0
    and every void blank. A missing tile taken as open sea is blank in the
    grid a read gives."""
    z = np.add(np.asarray(analysis.grid.z, dtype=np.float64), 0.0)
    z[analysis.core.cls == VOID] = np.nan
    return z


def lineament_candidates(analysis: TerrainAnalysis, cfg: TerrainConfig | None = None,
                         progress: Callable[[float, str], None] | None = None) -> LineamentAnalysis:
    """Find the lineament candidates of an analysed window.

    ``cfg`` is the configuration, by default the one the window was
    analysed with; ``progress(fraction, label)``, when given, hears the
    stage start. See the module for the method.
    """
    cfg = analysis.settings if cfg is None else cfg
    s = _settings(cfg)
    if progress is not None:
        progress(0.0, phrase("terrain.stage_lineaments"))
    core = analysis.core
    rows, cols = core.rows, core.cols
    r0, r1, c0, c1 = core.shown
    metric = analysis.metric
    mid = min((r0 + r1) // 2, rows - 1)
    dx0 = float(metric.dx[mid])
    dy0 = float(metric.dy[mid])
    frame = (dx0, dy0)
    cell = (dx0 + dy0) * 0.5
    ratio = s["lineament_smoothing_m"] / cell
    passes = math.floor((2.0 * ratio) * ratio + 0.5)
    half = max(1, math.floor((s["lineament_contrast_km"] * 500.0) / cell + 0.5))
    summary = {"passes": passes, "contrast_cells": half, "centre_cells": 0, "kept_cells": 0, "lines": 0,
               "pieces": 0, "candidates": 0, "valleys": 0, "ridges": 0, "linked": 0, "length_m": 0.0,
               "threshold": math.nan}
    if rows < 3 or cols < 3:
        return _empty(cfg, core.shown, frame, summary)

    # The tensor of the shading
    zs = binomial_smooth(_heights(analysis), passes)
    txx, tyy, txy = _edge_tensor(zs, metric, cfg.hillshade_panel_azimuths_deg, cfg.hillshade_altitude_deg,
                                 cfg.hillshade_z_factor)
    strength = txx + tyy
    ax = txx - tyy
    ay = txy + txy
    del txx, tyy, txy
    # The floor on the strength: to first order it is 2 (k cos alt)^2 for
    # ground bending by k per metre across a line
    bend_m = s["lineament_min_curvature_per_km"] / 1000.0
    scaled = bend_m * sin_cos_deg(cfg.hillshade_altitude_deg)[1]
    floor = 2.0 * (scaled * scaled)
    # The centreline, found a band of rows at a time: every step is cell by
    # cell, so the bands give what the whole grid would
    padded = np.pad(strength, 1, constant_values=np.nan).ravel()
    flat_s = strength.ravel()
    land = (core.cls == LAND).ravel()
    flat_ax = ax.ravel()
    flat_ay = ay.ravel()
    band = max(1, _BAND_CELLS // cols)
    found = []
    lined = 0
    for b0 in range(0, rows, band):
        lo, hi = b0 * cols, min(rows, b0 + band) * cols
        s_b, ax_b, ay_b = flat_s[lo:hi], flat_ax[lo:hi], flat_ay[lo:hi]
        with np.errstate(invalid="ignore"):
            m2 = ax_b * ax_b + ay_b * ay_b
            line = land[lo:hi] & (s_b >= floor) & (s_b > 0.0) & (m2 > 0.0)
        at = np.flatnonzero(line)
        lined += int(at.size)
        if at.size:
            found.append(_centreline(at + lo, ax_b[at], ay_b[at], m2[at], padded, flat_s, cols))
        del s_b, ax_b, ay_b, m2, line, at
    del padded, land, flat_ax, flat_ay, ax, ay
    if lined == 0:
        return _empty(cfg, core.shown, frame, summary)
    idx, nx, ny, here = (np.concatenate([part[k] for part in found]) for k in range(4))
    del found
    rr, cc = np.divmod(idx, cols)
    summary["centre_cells"] = int(idx.size)

    # Each weighed against the mean strength around it
    finite = np.isfinite(flat_s).reshape(rows, cols)
    level = np.where(finite, flat_s.reshape(rows, cols), 0.0)
    total = np.zeros((rows + 1, cols + 1))
    total[1:, 1:] = np.cumsum(np.cumsum(level, axis=1), axis=0)
    counts = np.zeros((rows + 1, cols + 1), dtype=np.int64)
    counts[1:, 1:] = np.cumsum(np.cumsum(finite, axis=1, dtype=np.int64), axis=0)
    del level, finite, flat_s
    ra = np.maximum(rr - half, 0)
    rb = np.minimum(rr + half + 1, rows)
    ca = np.maximum(cc - half, 0)
    cb = np.minimum(cc + half + 1, cols)
    box = ((total[rb, cb] - total[ra, cb]) - total[rb, ca]) + total[ra, ca]
    many = ((counts[rb, cb] - counts[ra, cb]) - counts[rb, ca]) + counts[ra, ca]
    del total, counts, ra, rb, ca, cb
    with np.errstate(invalid="ignore", divide="ignore"):
        relative = np.where(box > 0.0, here / (box / many), np.nan)
    inside = (rr >= r0) & (rr < r1) & (cc >= c0) & (cc < c1)
    share = s["lineament_share"]
    threshold = display_range(relative[inside], 1.0 - share, 1.0 - share)[0]
    summary["threshold"] = threshold
    if not math.isfinite(threshold):
        return _empty(cfg, core.shown, frame, summary)
    with np.errstate(invalid="ignore"):
        keep = np.flatnonzero(relative >= threshold)
    idx, rr, cc, nx, ny = idx[keep], rr[keep], cc[keep], nx[keep], ny[keep]

    # Valley or ridge, by the curvature across the line
    zp = np.pad(zs, 1, constant_values=np.nan).ravel()
    del zs
    width = cols + 2
    at = (rr + 1) * width + (cc + 1)
    dxr = np.asarray(metric.dx, dtype=np.float64)[rr]
    dyr = np.asarray(metric.dy, dtype=np.float64)[rr]
    z0 = zp[at]
    with np.errstate(invalid="ignore"):
        zxx = ((zp[at + 1] - 2.0 * z0) + zp[at - 1]) / (dxr * dxr)
        zyy = ((zp[at + width] - 2.0 * z0) + zp[at - width]) / (dyr * dyr)
        zxy = ((zp[at + width + 1] - zp[at + width - 1]) - (zp[at - width + 1] - zp[at - width - 1])) / (
            (4.0 * dxr) * dyr)
        bend = (((zxx * nx) * nx) + (((2.0 * zxy) * nx) * ny)) + ((zyy * ny) * ny)
    del zp, at, dxr, dyr, z0, zxx, zyy, zxy
    kind = np.where(bend > 0.0, VALLEY, np.where(bend < 0.0, RIDGE, 0))
    keep = np.flatnonzero(kind != 0)
    idx, rr, cc, nx, ny, kind = idx[keep], rr[keep], cc[keep], nx[keep], ny[keep], kind[keep]
    summary["kept_cells"] = int(idx.size)
    if idx.size == 0:
        return _empty(cfg, core.shown, frame, summary)

    # Lines: neighbouring cells of one kind whose directions agree
    labels = _lines(idx, rr, cc, nx, ny, kind, rows, cols, sin_cos_deg(s["lineament_turn_deg"])[1])
    order = np.argsort(labels, kind="stable")
    starts = np.concatenate(([0], np.flatnonzero(np.diff(labels[order])) + 1))
    summary["lines"] = int(starts.size)

    # Straight pieces of each line long enough to hold one: no piece spans
    # more than the diagonal of its line's box of cells
    shortest = s["lineament_piece_m"]
    r_sorted = rr[order]
    c_sorted = cc[order]
    ey = (np.maximum.reduceat(r_sorted, starts) - np.minimum.reduceat(r_sorted, starts)).astype(np.float64) * dy0
    ex = (np.maximum.reduceat(c_sorted, starts) - np.minimum.reduceat(c_sorted, starts)).astype(np.float64) * dx0
    reach = np.sqrt(ey * ey + ex * ex)
    ends = np.append(starts[1:], order.size)
    pieces: list[tuple] = []
    for g in np.flatnonzero(reach >= shortest):
        members = order[starts[g]:ends[g]]
        _straight_pieces(rr[members], cc[members], int(kind[members[0]]), dx0, dy0,
                         s["lineament_straight_m"], shortest, pieces)
    summary["pieces"] = len(pieces)

    # Linked along one line, cut to the square shown
    linked = _link(pieces, s["lineament_link_angle_deg"], s["lineament_link_offset_m"], s["lineament_link_gap_m"])
    bounds_xy = ((c0 - 0.5) * dx0, (c1 - 0.5) * dx0, (r0 - 0.5) * dy0, (r1 - 0.5) * dy0)
    out: list[Lineament] = []
    for kind_k, ox, oy, ux, uy, lo, hi, n_pieces, n_cells in linked:
        clipped = _clip(ox, oy, ux, uy, lo, hi, bounds_xy)
        if clipped is None:
            continue
        t0, t1 = clipped
        length = t1 - t0
        if not length >= s["lineament_min_length_m"]:
            continue
        strike = atan2_deg(ux, uy)
        if strike < 0.0:
            strike = strike + 180.0
        strike = strike + 0.0
        out.append(Lineament(
            id=len(out), kind=_KIND_NAME[kind_k], start=(ox + t0 * ux, oy + t0 * uy),
            end=(ox + t1 * ux, oy + t1 * uy), length_m=length, strike_deg=strike, pieces=n_pieces,
            cells=n_cells, cut=(t0 > lo) or (t1 < hi)))

    rose_v = [0.0] * ROSE_BANDS
    rose_r = [0.0] * ROSE_BANDS
    count_v = [0] * ROSE_BANDS
    count_r = [0] * ROSE_BANDS
    total_length = 0.0
    for item in out:
        band = min(ROSE_BANDS - 1, math.floor(item.strike_deg / 10.0))
        if item.kind == "valley":
            rose_v[band] += item.length_m
            count_v[band] += 1
        else:
            rose_r[band] += item.length_m
            count_r[band] += 1
        total_length += item.length_m
    summary.update(candidates=len(out), valleys=sum(count_v), ridges=sum(count_r),
                   linked=sum(1 for item in out if item.pieces > 1), length_m=total_length)
    if progress is not None:
        progress(1.0, phrase("terrain.stage_lineaments"))
    return LineamentAnalysis(tuple(out), tuple(rose_v), tuple(rose_r), tuple(count_v), tuple(count_r), frame,
                             core.shown, summary, cfg)


def _centreline(idx: np.ndarray, a_x: np.ndarray, a_y: np.ndarray, m2: np.ndarray, padded: np.ndarray,
                flat_s: np.ndarray, cols: int) -> tuple[np.ndarray, ...]:
    """Of the line cells ``idx`` (flat indices into the grid, ascending),
    with their doubled angle (``a_x``, ``a_y``, of square length ``m2``),
    those where the strength peaks across the line, as ``(idx, nx, ny,
    here)``: the cells, the unit vector across the line at each and the
    strength there. ``padded`` is the strength with a border of NaN, flat.
    Canny's thinning, the strength on each side read between the two
    neighbouring cells the direction falls between."""
    rr, cc = np.divmod(idx, cols)
    # The direction across the line at each cell, from its doubled angle
    m = np.sqrt(m2)
    c2 = a_x / m
    c2 = np.where(c2 > 1.0, 1.0, np.where(c2 < -1.0, -1.0, c2))      # a rounding past 1 makes no NaN
    nx = np.sqrt((1.0 + c2) * 0.5)
    ny = np.sqrt((1.0 - c2) * 0.5)
    ny = np.where(a_y < 0.0, -ny, ny)
    del m, c2
    width = cols + 2
    at = (rr + 1) * width + (cc + 1)
    anx = np.abs(nx)
    any_ = np.abs(ny)
    major_x = anx >= any_
    sx = np.where(nx < 0.0, -1, 1)
    sy = np.where(ny < 0.0, -1, 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        frac = np.where(major_x, any_ / anx, anx / any_)
    step_a = np.where(major_x, sx, sy * width)
    step_d = sy * width + sx
    here = flat_s[idx]
    with np.errstate(invalid="ignore"):
        a_plus = padded[at + step_a]
        ahead = a_plus + frac * (padded[at + step_d] - a_plus)
        a_minus = padded[at - step_a]
        behind = a_minus + frac * (padded[at - step_d] - a_minus)
        keep = np.flatnonzero((here > ahead) & (here >= behind))
    return idx[keep], nx[keep], ny[keep], here[keep]


def _lines(idx, rr, cc, nx, ny, kind, rows: int, cols: int, cos_turn: float) -> np.ndarray:
    """For every kept cell, the line it is on, named by its first cell in the
    order of ``idx``: cells next to each other (the eight neighbours) are on
    one line when they are of one kind and ``|n_i . n_j| >= cos_turn``."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    n = idx.size
    where = np.full(rows * cols, -1, dtype=np.int64)
    where[idx] = np.arange(n)
    src = []
    dst = []
    for dr, dc in ((0, 1), (1, -1), (1, 0), (1, 1)):
        r2 = rr + dr
        c2 = cc + dc
        ok = (r2 < rows) & (c2 >= 0) & (c2 < cols)
        j = np.full(n, -1, dtype=np.int64)
        j[ok] = where[r2[ok] * cols + c2[ok]]
        i = np.flatnonzero(j >= 0)
        j = j[i]
        joined = (kind[i] == kind[j]) & (np.abs(nx[i] * nx[j] + ny[i] * ny[j]) >= cos_turn)
        src.append(i[joined])
        dst.append(j[joined])
    del where
    a = np.concatenate(src)
    b = np.concatenate(dst)
    graph = coo_matrix((np.ones(a.size, dtype=np.int8), (a, b)), shape=(n, n))
    _, labels = connected_components(graph, directed=False)
    first = np.full(labels.max() + 1, n, dtype=np.int64)
    np.minimum.at(first, labels, np.arange(n))
    return first[labels]


def _straight_pieces(rr: np.ndarray, cc: np.ndarray, kind: int, dx0: float, dy0: float, tol: float,
                     shortest: float, out: list) -> None:
    """Cut one line, the cells ``(rr, cc)`` in the order found, into straight
    pieces, and add each piece to ``out`` as ``(length, kind, xa, ya, xb,
    yb, cells)``, its start the end further south (or west).

    A set of cells is fitted with the axis of its spread, from exact sums of
    whole numbers. When a cell lies more than ``tol`` from the axis, the set
    is cut across the axis at the cell furthest from it, if both sides then
    span ``shortest`` or more; otherwise the cells further than ``tol`` are
    dropped and the rest fitted again. A set spanning less than
    ``shortest`` is dropped.
    """
    r_all = rr.astype(np.int64)
    c_all = cc.astype(np.int64)
    stack = [np.arange(r_all.size)]
    while stack:
        sel = stack.pop()
        n = int(sel.size)
        if n < 2:
            continue
        r = r_all[sel]
        c = c_all[sel]
        sr = int(r.sum())
        sc = int(c.sum())
        crr = n * int((r * r).sum()) - sr * sr
        ccc = n * int((c * c).sum()) - sc * sc
        crc = n * int((r * c).sum()) - sr * sc
        nn = float(n * n)
        vyy = ((crr / nn) * dy0) * dy0
        vxx = ((ccc / nn) * dx0) * dx0
        vxy = ((crc / nn) * dx0) * dy0
        my = (sr / n) * dy0
        mx = (sc / n) * dx0
        half_sum = (vxx + vyy) * 0.5
        half_diff = (vxx - vyy) * 0.5
        l1 = half_sum + math.sqrt(half_diff * half_diff + vxy * vxy)
        if vxx >= vyy:
            ux, uy = l1 - vyy, vxy
        else:
            ux, uy = vxy, l1 - vxx
        norm = math.sqrt(ux * ux + uy * uy)
        if not norm > 0.0:
            continue
        ux = ux / norm
        uy = uy / norm
        x = c * dx0
        y = r * dy0
        t = (x - mx) * ux + (y - my) * uy
        off = np.abs((y - my) * ux - (x - mx) * uy)
        lo = float(t.min())
        hi = float(t.max())
        if hi - lo < shortest:
            continue
        k = int(np.argmax(off))
        if off[k] > tol:
            cut = t[k]
            left = t <= cut
            right = ~left
            span_l = float(t[left].max() - t[left].min()) if left.any() else 0.0
            span_r = float(t[right].max() - t[right].min()) if right.any() else 0.0
            if span_l >= shortest and span_r >= shortest:
                stack.append(sel[left])
                stack.append(sel[right])
            else:
                near = off <= tol
                if near.any():
                    stack.append(sel[near])
            continue
        xa, ya = mx + lo * ux, my + lo * uy
        xb, yb = mx + hi * ux, my + hi * uy
        if (yb - ya) < 0.0 or ((yb - ya) == 0.0 and (xb - xa) < 0.0):
            xa, ya, xb, yb = xb, yb, xa, ya
        out.append((hi - lo, kind, xa, ya, xb, yb, n))


def _link(pieces: list[tuple], angle_deg: float, offset_m: float, gap_m: float) -> list[tuple]:
    """Link the pieces lying along one line into candidates.

    The pieces are taken longest first (then by kind and their ends, so
    that the order is total). Each is linked into the first candidate so
    far of its kind whose direction differs from its own by no more than
    ``angle_deg``, from whose line neither of its ends lies more than
    ``offset_m``, and whose span along that line it meets or comes within
    ``gap_m`` of; the candidate's span then grows to take it in, along the
    candidate's own line. A piece linked to none starts a candidate.

    Each candidate is ``(kind, ox, oy, ux, uy, lo, hi, pieces, cells)``:
    its line through ``(ox, oy)`` in the direction ``(ux, uy)``, from ``lo``
    to ``hi`` metres along it.
    """
    order = sorted(pieces, key=lambda p: (-p[0], p[1], p[2], p[3], p[4], p[5]))
    sin_angle = sin_cos_deg(angle_deg)[0]
    n = len(order)
    kind = np.zeros(n, dtype=np.int64)
    ox = np.zeros(n)
    oy = np.zeros(n)
    ux = np.zeros(n)
    uy = np.zeros(n)
    lo = np.zeros(n)
    hi = np.zeros(n)
    n_pieces = np.zeros(n, dtype=np.int64)
    n_cells = np.zeros(n, dtype=np.int64)
    k = 0
    for length, kind_p, xa, ya, xb, yb, cells in order:
        vx = (xb - xa) / length
        vy = (yb - ya) / length
        if k:
            sl = slice(0, k)
            kx, ky, kox, koy = ux[sl], uy[sl], ox[sl], oy[sl]
            cross = np.abs(kx * vy - ky * vx)
            d_a = np.abs((ya - koy) * kx - (xa - kox) * ky)
            d_b = np.abs((yb - koy) * kx - (xb - kox) * ky)
            t_a = (xa - kox) * kx + (ya - koy) * ky
            t_b = (xb - kox) * kx + (yb - koy) * ky
            # the lesser and the greater by an explicit test, as the browser
            # takes them, so that a tie of +0 and -0 goes the same way
            first = t_a <= t_b
            p_lo = np.where(first, t_a, t_b)
            p_hi = np.where(first, t_b, t_a)
            fits = ((kind[sl] == kind_p) & (cross <= sin_angle) & (d_a <= offset_m) & (d_b <= offset_m)
                    & ~((p_lo - hi[sl]) > gap_m) & ~((lo[sl] - p_hi) > gap_m))
            found = np.flatnonzero(fits)
            if found.size:
                j = int(found[0])
                if p_lo[j] < lo[j]:
                    lo[j] = p_lo[j]
                if p_hi[j] > hi[j]:
                    hi[j] = p_hi[j]
                n_pieces[j] += 1
                n_cells[j] += cells
                continue
        kind[k], ox[k], oy[k], ux[k], uy[k] = kind_p, xa, ya, vx, vy
        lo[k], hi[k], n_pieces[k], n_cells[k] = 0.0, length, 1, cells
        k += 1
    return [(int(kind[j]), float(ox[j]), float(oy[j]), float(ux[j]), float(uy[j]), float(lo[j]), float(hi[j]),
             int(n_pieces[j]), int(n_cells[j])) for j in range(k)]


def _clip(ox: float, oy: float, ux: float, uy: float, lo: float, hi: float,
          bounds: tuple[float, float, float, float]) -> tuple[float, float] | None:
    """The span ``(t0, t1)`` of the line ``(ox, oy) + t (ux, uy)``, ``lo <= t
    <= hi``, inside the rectangle ``bounds`` (west, east, south, north), or
    None when it misses it."""
    west, east, south, north = bounds
    t0, t1 = lo, hi
    for origin, along, low, high in ((ox, ux, west, east), (oy, uy, south, north)):
        if along == 0.0:
            if origin < low or origin > high:
                return None
            continue
        ta = (low - origin) / along
        tb = (high - origin) / along
        if ta > tb:
            ta, tb = tb, ta
        if ta > t0:
            t0 = ta
        if tb < t1:
            t1 = tb
    if t1 < t0:
        return None
    return t0, t1


# --- what is said of them, and the download


def lineament_lonlat(result: LineamentAnalysis, lons, lats, point: tuple[float, float]) -> tuple[float, float]:
    """A point of the window's frame as longitude and latitude, read between
    the centres of the two columns and the two rows it lies between (or
    beyond the last two, at the window's edge)."""
    lons = np.asarray(lons, dtype=np.float64)
    lats = np.asarray(lats, dtype=np.float64)
    dx, dy = result.frame
    col = point[0] / dx
    row = point[1] / dy
    i = min(max(math.floor(col), 0), lons.size - 2)
    j = min(max(math.floor(row), 0), lats.size - 2)
    lon = float(lons[i]) + (col - i) * (float(lons[i + 1]) - float(lons[i]))
    lat = float(lats[j]) + (row - j) * (float(lats[j + 1]) - float(lats[j]))
    return lon, lat


def _azimuths(cfg: TerrainConfig) -> str:
    return and_join([f"{float(azimuth):g}°" for azimuth in cfg.hillshade_panel_azimuths_deg])


def lineament_captions(result: LineamentAnalysis, where: str) -> dict[str, str]:
    """The titles and captions of the lineament map and its rose, in the
    catalogue's words, with what the figures draw inside them: the note
    that the candidates are inferred from terrain (``figure_note``) and the
    heading of each of the rose's panels, its count and its length."""
    cfg = result.settings
    common = {"length": float(cfg.lineament_min_length_m), "smoothing": float(cfg.lineament_smoothing_m),
              "azimuths": _azimuths(cfg)}
    if result.lineaments:
        caption = phrase("terrain.caption_lineaments", valleys=result.summary["valleys"],
                         ridges=result.summary["ridges"], **common)
    else:
        caption = phrase("terrain.caption_lineaments_none", **common)
    return {
        "title_lineaments": phrase("terrain.title_lineaments", where=where),
        "title_rose": phrase("terrain.title_rose", where=where),
        "lineaments": caption,
        "rose": phrase("terrain.caption_rose"),
        "figure_note": phrase("terrain.figure_note_lineaments"),
        "rose_valleys": phrase("terrain.rose_valleys", count=sum(result.rose_valleys),
                               km=_in_order(result.rose_valley_m) / 1000.0),
        "rose_ridges": phrase("terrain.rose_ridges", count=sum(result.rose_ridges),
                              km=_in_order(result.rose_ridge_m) / 1000.0),
    }


def _in_order(values: Sequence[float]) -> float:
    """A sum taken one value at a time from 0, as the browser takes it:
    from Python 3.12, sum() of floats is compensated, which can differ in
    the last bit."""
    total = 0.0
    for value in values:
        total = total + value
    return total


def lineament_geojson(result: LineamentAnalysis, lons, lats, meta: Mapping) -> str:
    """The candidates shown, as GeoJSON text written by hand, without
    whitespace, in a fixed key order, so that both engines write the same
    bytes, as :func:`.terrain_analysis.drainage_geojson` writes the drainage
    lines.

    ``lons`` and ``lats`` are the analysed window's cell centres. ``meta``
    holds ``label``, ``figure_credit``, ``notice``, ``surface``, ``radius``
    and ``centre`` as the drainage lines' does. Each feature's number is
    the property ``lineament``, never ``id``, for the reason the drainage
    lines give. Coordinates have six decimals; lengths and strikes one.
    """
    cfg = result.settings
    centre = meta["centre"]
    description = phrase("terrain.lineament_geojson_description", label=meta["label"],
                         length=float(cfg.lineament_min_length_m), radius=float(meta["radius"]),
                         where=centre.label, smoothing=float(cfg.lineament_smoothing_m),
                         azimuths=_azimuths(cfg), surface=meta["surface"])
    out = ['{"type":"FeatureCollection","description":', _json_text(description),
           ',"attribution":', _json_text(meta["figure_credit"])]
    if meta.get("notice"):
        out += [',"notice":', _json_text(meta["notice"])]
    out += [f',"min_length_m":{float(cfg.lineament_min_length_m):g}', f',"radius_km":{float(meta["radius"]):g}',
            f',"centre":[{float(centre.lon):.6f},{float(centre.lat):.6f}],"features":[']
    for n, item in enumerate(result.lineaments):
        a = lineament_lonlat(result, lons, lats, item.start)
        b = lineament_lonlat(result, lons, lats, item.end)
        out.append(
            ("," if n else "")
            + f'{{"type":"Feature","properties":{{"lineament":{item.id},"kind":{_json_text(item.kind)},'
            + f'"length_m":{item.length_m:.1f},"strike_deg":{item.strike_deg:.1f},"pieces":{item.pieces},'
            + f'"cut":{"true" if item.cut else "false"}}},"geometry":{{"type":"LineString","coordinates":'
            + f'[[{a[0]:.6f},{a[1]:.6f}],[{b[0]:.6f},{b[1]:.6f}]]}}}}'
        )
    out.append("]}")
    return "".join(out)

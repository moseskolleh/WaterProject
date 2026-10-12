"""Terrain analysis: the drainage, shading, wetness and curvature worked out from an elevation model's heights alone."""

from __future__ import annotations

import math
from collections.abc import Iterator, Sequence

import numpy as np

from .elevation import RowMetric, sin_cos_deg

#: The cell classes the routing block holds in ``cls``; the surface block
#: reads only LAND. (The routing block defines the same three names.)
VOID, LAND, SEA = 0, 1, 2


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
    """The metric's east-west and north-south cell sizes, one per row."""
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


def hillshade_layer(p, q, azimuth_deg: float, altitude_deg: float, z_factor: float = 1.0) -> np.ndarray:
    """The ground lit by a sun at ``azimuth_deg`` (clockwise from north)
    and ``altitude_deg`` above the horizon: the cosine of the angle between
    the sun and the ground's normal, 0 in shadow to 1 facing the sun.

    This is GDAL's hillshade with Horn's gradients (``gdaldem hillshade``),
    written from ``p`` and ``q`` of :func:`horn_gradients`, scaled by
    ``z_factor``. A slope turned away from the sun is 0, not negative, and
    NaN stays NaN where the gradient is not defined, rather than reading as
    flat ground in shadow.
    """
    flat_p, flat_q, shape = _flat_pair(p, q)
    zf = float(z_factor)
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
                               z_factor: float = 1.0) -> np.ndarray:
    """The ground lit from several azimuths at once, each sun weighted by
    how squarely it lights the local slope: ``gdaldem hillshade
    -multidirectional`` exactly when ``azimuths`` is 225, 270, 315 and 360.

    GDAL weights each azimuth by ``(p*sin az + q*cos az)**2``, the square
    of the slope's component towards that sun (its fixed weights for the
    four azimuths are these terms written out), so a slope is shaded mostly
    by the suns that light it across. That is GDAL's local-aspect rule, not
    Mark (1992), who weights by an aspect smoothed over a kilometre. Flat
    ground, where every weight is 0, is lit at the sine of the altitude.
    The azimuths are taken in the order given.
    """
    flat_p, flat_q, shape = _flat_pair(p, q)
    zf = float(z_factor)
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
    if not floor > 0.0:
        raise ValueError(f"flat_tan_slope must be a positive slope, not {flat_tan_slope!r}")
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
        twi[r0:r1][defined] = np.log(band_arg[defined])
        floored[r0:r1] = defined & ~(band_tanb >= floor)
    return arg, twi, floored


def _curvature_cells(metric: RowMetric, spacing_m: float) -> int:
    """How many cells apart the curvature samples are: ``spacing_m`` in
    cells of the middle row, rounded half up, at least 1 (3 at 1
    arc-second and 1 at 3 for the default 90 m)."""
    dx = np.asarray(metric.dx, dtype=np.float64)
    dy = np.asarray(metric.dy, dtype=np.float64)
    spacing = float(spacing_m)
    if not (math.isfinite(spacing) and spacing > 0.0):
        raise ValueError(f"the curvature spacing must be a positive number of metres, not {spacing_m!r}")
    mid = dx.size // 2
    return max(1, math.floor(spacing / ((float(dx[mid]) + float(dy[mid])) / 2.0) + 0.5))


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
    if not 0.0 <= lo <= hi <= 1.0:
        raise ValueError(f"a display range needs 0 <= lo <= hi <= 1, not lo={lo!r} and hi={hi!r}")
    v = np.asarray(values, dtype=np.float64).ravel()
    v = v[np.isfinite(v)] + 0.0
    n = int(v.size)
    if n == 0:
        return math.nan, math.nan
    i = math.floor(lo * (n - 1))
    j = math.floor(hi * (n - 1))
    chosen = np.partition(v, (i, j) if i != j else i)
    return float(chosen[i]), float(chosen[j])

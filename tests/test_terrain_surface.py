"""The surface kernels of the terrain analysis: slope, shading, wetness,
curvature and the numbers the figures are drawn between.

mapping/terrain_analysis.py works these out with additions,
multiplications, divisions and square roots in a stated order, and its
sines and cosines through sin_cos_deg, so that the browser's engine gives
the same bits; the parity suite holds the two together. These tests hold
the Python kernels to what each layer means: closed forms for planes, a
cone and a quadratic surface, GDAL's own formula for the composite shade
(and gdaldem itself where it is installed), and the rules for voids, flats
and the edge.
"""

from __future__ import annotations

import math
import random

import numpy as np
import pytest

from groundwater.config import TerrainConfig
from groundwater.mapping.elevation import row_metric, sin_cos_deg
from groundwater.mapping.terrain import _contour_interval
from groundwater.mapping.terrain_analysis import (
    LAND,
    SEA,
    VOID,
    contour_interval,
    curvatures,
    display_range,
    hillshade_layer,
    horn_gradients,
    multidirectional_hillshade,
    wetness_index,
)

ARCSEC = 1.0 / 3600.0


def _lattice(rows: int, cols: int, step: float = ARCSEC, lat0: float = 8.5):
    """Cell centres of a geographic grid at 8.5 N, and its row metric."""
    lons = -11.5 + np.arange(cols) * step
    lats = lat0 + np.arange(rows) * step
    return lons, lats, row_metric(lons, lats)


def _index_plane(rows: int, cols: int, a: float, b: float, base: float = 500.0) -> np.ndarray:
    """``base + a*c + b*r``: a plane rising ``a`` metres a column eastwards
    and ``b`` a row northwards. Horn's rule is exact on it, giving
    ``p = a/dx[r]`` and ``q = b/dy[r]`` on each row."""
    c = np.arange(cols, dtype=float)[None, :]
    r = np.arange(rows, dtype=float)[:, None]
    return base + a * c + b * r


def _cos_incidence(p: float, q: float, azimuth: float, altitude: float) -> float:
    """The textbook illumination of a slope ``(p, q)``, from libm's trig."""
    az, alt = math.radians(azimuth), math.radians(altitude)
    return (math.sin(alt) - math.cos(alt) * (p * math.sin(az) + q * math.cos(az))) / math.sqrt(1 + p * p + q * q)


def _ring(a: np.ndarray, width: int = 1) -> np.ndarray:
    """The cells of ``a`` within ``width`` of its edge."""
    edge = np.ones(a.shape, dtype=bool)
    edge[width:-width, width:-width] = False
    return a[edge]


# ---------------------------------------------------------------------------
# Hillshade
# ---------------------------------------------------------------------------

#: Eight facets, by the compass direction each descends towards.
FACINGS = (0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0)


def test_hillshade_lights_slopes_facing_the_stated_azimuth():
    """A slope facing the sun is the brightest of eight and the one facing
    away the darkest, for suns at four azimuths, and every value is the
    cosine of incidence. The old shading measured its azimuth a quarter
    turn out, so 315 lit the north-east and relief along every north-south
    ridge read inverted; a sun swapped for its mirror image or a shade
    rescaled from (cos i + 1) / 2 fails here too. A slope turned fully
    away from the sun is 0, never negative and never -0."""
    rows = cols = 5
    _, _, metric = _lattice(rows, cols)
    mid = rows // 2
    rise = 0.4
    facets = {}
    for facing in FACINGS:
        s, c = math.sin(math.radians(facing)), math.cos(math.radians(facing))
        a, b = -rise * s * metric.dx[mid], -rise * c * metric.dy[mid]
        p, q, tanb = horn_gradients(_index_plane(rows, cols, a, b), metric)
        # Horn's rule on a plane: the rise over each row's own cell size
        want_p = np.full((rows, cols), np.nan)
        want_q = np.full((rows, cols), np.nan)
        want_p[1:-1, 1:-1] = (a / metric.dx[1:-1])[:, None]
        want_q[1:-1, 1:-1] = (b / metric.dy[1:-1])[:, None]
        np.testing.assert_allclose(p, want_p, rtol=1e-12, atol=1e-15)
        np.testing.assert_allclose(q, want_q, rtol=1e-12, atol=1e-15)
        np.testing.assert_allclose(tanb[1:-1, 1:-1], rise, rtol=1e-5)
        facets[facing] = (p, q, want_p, want_q)
    for azimuth in (0.0, 90.0, 225.0, 315.0):
        lit = {}
        for facing, (p, q, want_p, want_q) in facets.items():
            shade = hillshade_layer(p, q, azimuth, 45.0)
            assert np.isnan(_ring(shade)).all()
            inner = shade[1:-1, 1:-1]
            for r in range(1, rows - 1):
                for c in range(1, cols - 1):
                    want = _cos_incidence(want_p[r, c], want_q[r, c], azimuth, 45.0)
                    assert abs(shade[r, c] - want) <= 1e-12, (azimuth, facing, r, c)
            lit[facing] = float(inner.mean())
        assert max(lit, key=lit.__getitem__) == azimuth % 360.0, (azimuth, lit)
        assert min(lit, key=lit.__getitem__) == (azimuth + 180.0) % 360.0, (azimuth, lit)
    # a slope of 2 (63 degrees) facing away from a 45-degree sun is in shadow
    steep = _index_plane(rows, cols, 0.0, 2.0 * metric.dy[mid])   # rises north: faces south
    p, q, _ = horn_gradients(steep, metric)
    shadow = hillshade_layer(p, q, 0.0, 45.0)[1:-1, 1:-1]
    assert (shadow == 0.0).all() and (np.copysign(1.0, shadow) == 1.0).all()


def test_every_hillshade_panel_is_lit_from_above():
    """Every one-direction panel (and the layers step 4.2 starts from) is
    lit from the northern half of the sky, where relief does not read as
    inverted: a slope facing north is never darker than the same slope
    facing south. Between them the panels light every strike within 22.5
    degrees of square on, so a lineament of any strike shows in one of
    them. The composite's 225 is the reason the panels are a list of their
    own: lit from the lower left, a panel of it would invert the relief."""
    cfg = TerrainConfig()
    panels = cfg.hillshade_panel_azimuths_deg
    assert len(panels) == 4
    north_facing = (np.array([0.0]), np.array([-0.3]))
    south_facing = (np.array([0.0]), np.array([0.3]))
    for azimuth in panels:
        _, cos_az = sin_cos_deg(azimuth)
        assert cos_az >= 0.0, azimuth
        north = hillshade_layer(*north_facing, azimuth, cfg.hillshade_altitude_deg, cfg.hillshade_z_factor)
        south = hillshade_layer(*south_facing, azimuth, cfg.hillshade_altitude_deg, cfg.hillshade_z_factor)
        assert north[0] >= south[0], azimuth
    for strike in range(180):
        across = [abs((azimuth - strike) % 180.0 - 90.0) for azimuth in panels]
        assert min(across) <= 22.5, strike
    assert sin_cos_deg(225.0)[1] < 0.0 and 225.0 in cfg.hillshade_azimuths_deg


def _cone(rows: int, cols: int, metric, peak: float = 200.0, fall: float = 0.3, top: float = 165.0) -> np.ndarray:
    """A cone falling ``fall`` metres a metre from the middle cell, cut flat
    at ``top``: every aspect, and a level summit."""
    r0, c0 = rows // 2, cols // 2
    r = np.arange(rows, dtype=float)[:, None]
    c = np.arange(cols, dtype=float)[None, :]
    east = (c - c0) * metric.dx[:, None]
    north = (r - r0) * metric.dy[r0]
    z = peak - fall * np.sqrt(east * east + north * north)
    return np.minimum(z, top)


def _gdal_multidirectional(p: float, q: float, altitude: float) -> float:
    """GDALHillshadeMultiDirectionalAlg, in GDAL's own variables: x is the
    westward rise (GDAL takes west minus east) and y the northward, the
    fixed weights for 225, 270, 315 and 360, and the value scaled from
    GDAL's 1..255 back to 0..1."""
    x, y = -p, q
    alt = math.radians(altitude)
    sin_alt, cos_alt = math.sin(alt), math.cos(alt)
    xx_plus_yy = x * x + y * y
    if xx_plus_yy == 0.0:
        return sin_alt
    cos225 = math.cos(math.radians(225.0))
    val225 = max(0.0, sin_alt + (x - y) * cos225 * cos_alt)
    val270 = max(0.0, sin_alt - x * cos_alt)
    val315 = max(0.0, sin_alt + (x + y) * cos225 * cos_alt)
    val360 = max(0.0, sin_alt - y * cos_alt)
    weight_225 = 0.5 * xx_plus_yy - x * y
    weight_270 = x * x
    weight_315 = xx_plus_yy - weight_225
    weight_360 = y * y
    weighted = weight_225 * val225 + weight_270 * val270 + weight_315 * val315 + weight_360 * val360
    return weighted / (2.0 * xx_plus_yy) / math.sqrt(1.0 + xx_plus_yy)


def test_multidirectional_hillshade_matches_the_gdal_weights_on_a_cone():
    """The composite is gdaldem -multidirectional: GDAL's fixed weights for
    225, 270, 315 and 360 degrees are the squares of each sun's component
    of the slope, and a cone shows every aspect. Weighting by Mark's
    smoothed aspect, normalising by anything but the weights' sum, or
    lighting a level summit at anything but the sine of the altitude
    fails here."""
    cfg = TerrainConfig()
    rows, cols = 31, 33
    _, _, metric = _lattice(rows, cols)
    p, q, _ = horn_gradients(_cone(rows, cols, metric), metric)
    shade = multidirectional_hillshade(p, q, cfg.hillshade_azimuths_deg, cfg.hillshade_altitude_deg)
    assert np.isnan(_ring(shade)).all()
    level = 0
    for r in range(1, rows - 1):
        for c in range(1, cols - 1):
            if p[r, c] == 0.0 and q[r, c] == 0.0:
                level += 1
                assert shade[r, c] == sin_cos_deg(cfg.hillshade_altitude_deg)[0]
                continue
            want = _gdal_multidirectional(p[r, c], q[r, c], cfg.hillshade_altitude_deg)
            assert abs(shade[r, c] - want) <= 1e-12, (r, c, shade[r, c], want)
    assert level >= 5, "the cone's cut summit should hold level cells"
    # every aspect is there: the slopes facing each of the four suns
    aspects = np.degrees(np.arctan2(-p, -q)) % 360.0
    assert all(np.any(np.abs(aspects - a) < 10.0) for a in (45.0, 135.0, 225.0, 315.0))


def test_multidirectional_hillshade_matches_gdaldem_where_it_is_installed():
    """Against gdaldem itself, run a row band at a time, because the kernel
    sizes every row's cells on the ellipsoid while gdaldem takes one scale
    for a raster (GDAL 3.11 and later would even pick a mean-latitude one
    on its own for a geographic file). Each three-row band is handed over
    in metres with an explicit scale of 1, so no version scales it again.
    gdaldem writes a byte, 1 + 254 times the shade rounded, from float32
    arithmetic and an approximate square root, so the two agree to that
    rounding and no more: half a grey level, and a hair for float32. The
    single sun of the topographic map is checked the same way."""
    gdal = pytest.importorskip("osgeo.gdal")
    gdal.UseExceptions()
    cfg = TerrainConfig()
    rows, cols = 13, 15
    _, _, metric = _lattice(rows, cols)
    # heights GDAL reads as float32 without rounding
    z = _cone(rows, cols, metric).astype(np.float32).astype(np.float64)
    p, q, _ = horn_gradients(z, metric)
    composite = multidirectional_hillshade(p, q, cfg.hillshade_azimuths_deg, cfg.hillshade_altitude_deg)
    single = hillshade_layer(p, q, 315.0, cfg.hillshade_altitude_deg)
    driver = gdal.GetDriverByName("MEM")
    for r in range(1, rows - 1):
        band = driver.Create("", cols, 3, 1, gdal.GDT_Float32)
        band.SetGeoTransform((0.0, float(metric.dx[r]), 0.0, 0.0, 0.0, -float(metric.dy[r])))
        band.GetRasterBand(1).WriteArray(z[r - 1:r + 2][::-1].astype(np.float32))  # north first
        for ours, options in ((composite, dict(multiDirectional=True)), (single, dict(azimuth=315.0))):
            out = gdal.DEMProcessing("", band, "hillshade", format="MEM", altitude=cfg.hillshade_altitude_deg,
                                     zFactor=1.0, scale=1.0, **options)
            grey = out.GetRasterBand(1).ReadAsArray().astype(float)[1, 1:-1]
            want = 1.0 + 254.0 * ours[r, 1:-1]
            assert np.all(np.abs(grey - want) <= 0.51), (r, options, grey, want)


def test_hillshade_of_a_void_window_is_nan_not_zero():
    """A cell whose 3x3 window meets a void, or the edge, has no slope, so
    its shade, slope and gradients are NaN: not 0, which draws a black
    shadow round every gap, not the sine of the altitude, which draws it
    as level ground, and not a slope from a stand-in height, which drew a
    cliff. A grid of voids is NaN throughout."""
    rows, cols = 9, 10
    _, _, metric = _lattice(rows, cols)
    z = _index_plane(rows, cols, 1.5, -0.7)
    z[4, 5] = np.nan
    p, q, tanb = horn_gradients(z, metric)
    layers = (p, q, tanb, hillshade_layer(p, q, 315.0, 45.0),
              multidirectional_hillshade(p, q, (225.0, 270.0, 315.0, 360.0), 45.0))
    beside = np.zeros((rows, cols), dtype=bool)
    beside[3:6, 4:7] = True
    edge = np.zeros((rows, cols), dtype=bool)
    edge[[0, -1], :] = True
    edge[:, [0, -1]] = True
    for layer in layers:
        assert np.isnan(layer[beside]).all()
        assert np.isnan(layer[edge]).all()
        assert np.isfinite(layer[~beside & ~edge]).all()
    voids = np.full((rows, cols), np.nan)
    p, q, tanb = horn_gradients(voids, metric)
    for layer in (p, q, tanb, hillshade_layer(p, q, 315.0, 45.0),
                  multidirectional_hillshade(p, q, (225.0, 270.0, 315.0, 360.0), 45.0)):
        assert np.isnan(layer).all()
    # an infinite height is no height either
    z[4, 5] = np.inf
    assert np.isnan(horn_gradients(z, metric)[2][beside]).all()


# ---------------------------------------------------------------------------
# Curvature
# ---------------------------------------------------------------------------

def _round_surface(rows: int, cols: int, metric, radius_m: float, sign: float) -> np.ndarray:
    """A dome (``sign`` +1) or a bowl (-1) of radius of curvature
    ``radius_m``, centred on the middle cell, in metres east and north."""
    r0, c0 = rows // 2, cols // 2
    east = (np.arange(cols, dtype=float)[None, :] - c0) * metric.dx[:, None]
    north = (np.arange(rows, dtype=float)[:, None] - r0) * metric.dy[r0]
    return 300.0 - sign * (east * east + north * north) / (2.0 * radius_m)


def test_curvature_of_a_dome_is_convex_and_diverging_and_of_a_bowl_concave_and_converging():
    """The signs are Florinsky's and Minar's: a dome is convex down the
    slope (profile positive: flow speeds up) and diverging across it
    (tangential positive), a bowl concave and converging (both negative).
    ESRI's legacy profile sign, or a sign lost in the leading minus, turns
    one of them over. Sea, a void, the summit's level ground and the
    margin k cells deep have no curvature."""
    cfg = TerrainConfig()
    rows, cols = 41, 43
    _, _, metric = _lattice(rows, cols)
    cls = np.full((rows, cols), LAND, dtype=np.uint8)
    cls[2:6, 30:36] = SEA
    for sign in (1.0, -1.0):
        z = _round_surface(rows, cols, metric, 2000.0, sign)
        z[35, 8] = np.nan
        cls_here = cls.copy()
        cls_here[35, 8] = VOID
        profile, tangential, k = curvatures(z, cls_here, metric, cfg.curvature_spacing_m, cfg.flat_tan_slope)
        assert k == 3
        defined = np.isfinite(profile)
        assert np.array_equal(defined, np.isfinite(tangential))
        assert defined.sum() > 500
        assert not defined[:k].any() and not defined[-k:].any()
        assert not defined[:, :k].any() and not defined[:, -k:].any()
        assert not defined[cls_here == SEA].any()
        assert not defined[35 - k:36 + k, 8 - k:9 + k][::k, ::k].any(), "a sample in the void"
        assert not defined[rows // 2, cols // 2], "the summit is level: no direction, no curvature"
        assert np.all(np.sign(profile[defined]) == sign)
        assert np.all(np.sign(tangential[defined]) == sign)
        # 1/R on level ground, less the slope's share: 4 cells east of the top
        r0, c0 = rows // 2, cols // 2
        w = 1.0 + (4.0 * float(metric.dx[r0]) / 2000.0) ** 2
        assert profile[r0, c0 + 4] == pytest.approx(sign / 2000.0 / w ** 1.5, rel=1e-3)
        assert tangential[r0, c0 + 4] == pytest.approx(sign / 2000.0 / w ** 0.5, rel=1e-3)


def test_curvature_of_a_paraboloid_matches_its_closed_form():
    """On a quadratic surface the Evans-Young differences are exact, so
    both curvatures equal their closed forms at every cell, with the
    samples k cells apart on each row's own cell size. A sample taken one
    cell apart while the spacing says three, a cell size from the wrong
    row, a cross term with its sign turned, or a slope term squared in the
    wrong place fails here. The spacing in cells is the stated metres in
    cells of the middle row, rounded: 3 at 1 arc-second and 1 at 3."""
    cfg = TerrainConfig()
    for step, k_want in ((ARCSEC, 3), (3 * ARCSEC, 1)):
        rows, cols = 33, 35
        _, _, metric = _lattice(rows, cols, step)
        r0, c0 = rows // 2, cols // 2
        a, b, c, d, e = 0.004, 0.002, 0.006, 0.3, -0.2      # metres per cell and per cell squared
        u = np.arange(cols, dtype=float)[None, :] - c0
        v = np.arange(rows, dtype=float)[:, None] - r0
        z = 250.0 + a * u * u + b * u * v + c * v * v + d * u + e * v
        cls = np.full((rows, cols), LAND, dtype=np.uint8)
        profile, tangential, k = curvatures(z, cls, metric, cfg.curvature_spacing_m, cfg.flat_tan_slope)
        assert k == k_want
        checked = 0
        for row in range(k, rows - k):
            dx, dy = float(metric.dx[row]), float(metric.dy[row])
            for col in range(k, cols - k):
                uu, vv = col - c0, row - r0
                p = (2 * a * uu + b * vv + d) / dx
                q = (2 * c * vv + b * uu + e) / dy
                rr = 2 * a / dx ** 2
                t = 2 * c / dy ** 2
                s = b / (dx * dy)
                g2 = p * p + q * q
                w = 1 + g2
                kv = -(p * p * rr + 2 * p * q * s + q * q * t) / (g2 * w ** 1.5)
                kh = -(q * q * rr - 2 * p * q * s + p * p * t) / (g2 * w ** 0.5)
                assert profile[row, col] == pytest.approx(kv, rel=1e-8, abs=1e-15), (step, row, col)
                assert tangential[row, col] == pytest.approx(kh, rel=1e-8, abs=1e-15), (step, row, col)
                checked += 1
        assert checked == (rows - 2 * k) * (cols - 2 * k)


# ---------------------------------------------------------------------------
# Wetness
# ---------------------------------------------------------------------------

def test_wetness_rises_downslope_and_uses_the_floor_on_flats():
    """Down a slope the area draining through a cell grows and the index
    with it; on level ground the slope is taken as the floor (counted, not
    NaN, so a swamp floor is drawn), and the argument is exactly the area
    over the mean cell side over the floored slope. Sea, voids and cells
    with no slope have no index. Dividing the area in m2 by one cell side,
    taking 0.01 m2 units as m2, or blanking flats fails here."""
    cfg = TerrainConfig()
    rows, cols = 14, 7
    _, _, metric = _lattice(rows, cols)
    # level ground in the south six rows, rising 0.5 m a row to the north
    z = 20.0 + 0.5 * np.maximum(np.arange(rows, dtype=float) - 5.0, 0.0)[:, None] * np.ones((1, cols))
    _, _, tanb = horn_gradients(z, metric)
    # every cell receives the whole column north of it: hand-made routing
    above = np.cumsum(metric.au_row[::-1])[::-1].astype(np.int64)
    area = np.repeat(above[:, None], cols, axis=1)
    cls = np.full((rows, cols), LAND, dtype=np.uint8)
    cls[2, 1] = SEA
    cls[8, 5] = VOID
    arg, twi, floored = wetness_index(area, cls, tanb, metric, cfg.flat_tan_slope)
    assert np.isnan(arg[2, 1]) and np.isnan(twi[2, 1]) and not floored[2, 1]
    assert np.isnan(arg[8, 5]) and np.isnan(twi[8, 5]) and not floored[8, 5]
    assert np.isnan(_ring(twi)).all() and not _ring(floored).any()
    for row in range(1, rows - 1):
        width = (float(metric.dx[row]) + float(metric.dy[row])) / 2.0
        slope = float(tanb[row, 3])
        tb = slope if slope >= cfg.flat_tan_slope else cfg.flat_tan_slope
        assert arg[row, 3] == (float(area[row, 3]) / 100.0) / width / tb, row
        assert twi[row, 3] == pytest.approx(math.log(arg[row, 3]), rel=1e-12)
        assert floored[row, 3] == (slope < cfg.flat_tan_slope)
    level = np.zeros((rows, cols), dtype=bool)
    level[1:5, 1:-1] = True
    level[2, 1] = False                                        # sea, not land
    assert np.array_equal(floored, level)
    # on the slope, each row south of another holds more water
    slope_rows = twi[6:-1, 3]
    assert np.all(np.diff(slope_rows) < 0.0), slope_rows
    # level ground below the slope is the wettest of all
    assert np.nanmin(twi[1:5, 1:-1]) > np.nanmax(twi[5:-1, 1:-1])


def test_the_wetness_display_range_is_chosen_on_the_exact_argument():
    """The figure's limits are the 2% and 98% elements of the exact
    argument, chosen before any logarithm is taken: neighbouring arguments
    can share one logarithm, and another engine's log may break such a tie
    the other way, so a range chosen on the index itself could pick a
    different element in each app. The choice ignores sea, voids, infinite
    values and the order the cells come in, and a -0 counts as 0."""
    # 600 arguments a few units in the last place apart near 1e10: about
    # sixteen of them share each value of the logarithm
    base = 1e10
    args = np.array([base + j * math.ulp(base) for j in range(600)])
    logs = np.log(args)
    assert len(np.unique(logs)) < len(np.unique(args)) // 4
    shuffled = args.copy()
    random.Random(7).shuffle(shuffled)
    lo, hi = display_range(np.concatenate([shuffled, [np.nan, np.inf, -np.inf]]), 0.02, 0.98)
    ordered = np.sort(args)
    n = args.size
    assert lo == ordered[math.floor(0.02 * (n - 1))]
    assert hi == ordered[math.floor(0.98 * (n - 1))]
    assert display_range(args, 0.02, 0.98) == (lo, hi)
    # from the kernel, on a grid: the range is two of its own arguments
    cfg = TerrainConfig()
    rows, cols = 12, 11
    _, _, metric = _lattice(rows, cols)
    rng = np.random.default_rng(5)
    z = np.round(rng.normal(40.0, 3.0, (rows, cols)), 1)
    _, _, tanb = horn_gradients(z, metric)
    area = (rng.integers(1, 400, (rows, cols)) * metric.au_row[:, None]).astype(np.int64)
    cls = np.where(rng.random((rows, cols)) < 0.1, SEA, LAND).astype(np.uint8)
    arg, twi, _ = wetness_index(area, cls, tanb, metric, cfg.flat_tan_slope)
    lo, hi = display_range(arg, 0.02, 0.98)
    finite = np.sort(arg[np.isfinite(arg)])
    assert (lo, hi) == (finite[math.floor(0.02 * (finite.size - 1))], finite[math.floor(0.98 * (finite.size - 1))])
    assert lo in arg and hi in arg
    assert math.log(lo) == pytest.approx(float(np.nanmin(twi[arg == lo])), rel=1e-12)
    assert display_range(np.array([-0.0, 0.0, -0.0]), 0.0, 1.0) == (0.0, 0.0)
    assert math.copysign(1.0, display_range(np.array([-0.0, 1.0]), 0.0, 0.0)[0]) == 1.0
    assert all(math.isnan(v) for v in display_range(np.array([np.nan, np.inf]), 0.02, 0.98))
    with pytest.raises(ValueError, match="lo <= hi"):
        display_range(args, 0.98, 0.02)


# ---------------------------------------------------------------------------
# Relief and contours
# ---------------------------------------------------------------------------

def test_relief_and_contours_ignore_infinite_values():
    """An infinite height is no height: the relief is taken over the finite
    heights, and an interval for a relief that is infinite, NaN, zero or
    negative is 10 m. Walking powers of ten up to an infinite relief raised
    OverflowError in Python and never ended in the browser; the walk has an
    end for any finite relief, however large."""
    z = np.array([[12.0, 62.0, np.inf], [-np.inf, np.nan, 30.0]])
    assert _contour_interval(z) == contour_interval(50.0) == 5.0
    for relief in (math.inf, -math.inf, math.nan, 0.0, -0.0, -3.0):
        assert contour_interval(relief) == 10.0, relief
    assert _contour_interval(np.full((2, 2), np.inf)) == 10.0
    assert _contour_interval(np.full((2, 2), 7.0)) == 10.0
    assert contour_interval(1e300) == 1e299
    assert contour_interval(np.float64(600.0)) == 100.0
    assert display_range(np.array([np.inf, 1.0, 2.0, -np.inf, np.nan]), 0.0, 1.0) == (1.0, 2.0)


def _old_contour_interval(z: np.ndarray) -> float:
    """terrain._contour_interval as it was before PR 4.1b, with log10."""
    finite = z[np.isfinite(z)]
    if finite.size == 0:
        return 10.0
    relief = float(finite.max() - finite.min())
    if relief <= 0:
        return 10.0
    target = relief / 12.0
    nice = 10 ** math.floor(math.log10(target))
    for mult in (10, 5, 2, 1):
        if nice * mult <= target * 2:
            return max(nice * mult, 1.0)
    return max(nice, 1.0)


def _near_a_knife_edge(relief: float) -> bool:
    """Whether a sixth of ``relief`` lies within a part in 1e9 of one of
    1, 2, 5, 10, ..., where log10's last bit could tip the old rule."""
    limit = (relief / 12.0) * 2.0
    for exponent in range(-4, 8):
        for step in (1, 2, 5):
            nice = step * 10.0 ** exponent
            if abs(limit - nice) <= 1e-9 * nice:
                return True
    return False


def test_the_contour_interval_is_unchanged_away_from_knife_edges():
    """The interval without log10 is the interval the topographic map
    always drew, for every relief from a centimetre to a hundred
    kilometres, so rebuilding the map on the shared rule moves no example
    figure's contours. The exception allowed for is a relief within a part
    in a billion of six times a round number, where the old rule hung on
    the last bit of a library's log10; there the new rule's answer is the
    round number itself, whatever the library."""
    rng = random.Random(41)
    reliefs = [float(v) for v in np.geomspace(0.01, 1e5, 4001)]
    reliefs += [rng.uniform(0.0, 3000.0) for _ in range(4000)]
    checked = 0
    for relief in reliefs:
        if _near_a_knife_edge(relief):
            continue
        z = np.array([[100.0, 100.0 + relief]])
        assert _contour_interval(z) == _old_contour_interval(z), relief
        checked += 1
    assert checked > 7900
    # on the edge itself the round number is the answer, and a hair below
    # it the next one down
    below = {10: 5, 20: 10, 50: 20, 100: 50, 200: 100, 500: 200, 1000: 500}
    for nice, smaller in below.items():
        relief = 6.0 * nice
        assert (relief / 12.0) * 2.0 == nice
        assert contour_interval(relief) == nice
        assert contour_interval(math.nextafter(relief, 0.0)) == smaller

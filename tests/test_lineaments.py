"""Lineament candidates: straight valleys and ridges found in the shading
(PLAN.md step 4.2, groundwater/mapping/lineaments.py).

The first half holds the Python module to its rules on windows built for
the purpose: valleys and ridges planted at known strikes in random relief
are found at their strike and of their kind, pieces that line up across a
short gap are linked and across a long one are not, flat ground has none,
sea is never a centreline, the square shown cuts a candidate cleanly, the
rose adds up, and the GeoJSON and the captions say what the candidates are.
The isotropy check (random terrain gives a rose with no preferred
direction) is marked slow.

The second half runs the browser's engine (C.lineamentCandidates and the
functions beside it in docs/js/gwt-core.js) in a Node vm on the same
windows and holds it to the Python one to the bit: every candidate, the
summary, the roses, the captions and the GeoJSON's bytes, on seeded windows
with voids, sea, thin grids and settings at their edges, and the
arctangent and the smoothing on their own.

The grids are south-first, as the analysis holds them: row 0 is the south
edge and north is row + 1.
"""

from __future__ import annotations

import dataclasses
import json
import math
import shutil
import struct
import subprocess
from pathlib import Path

import numpy as np
import pytest

from groundwater.config import TerrainConfig
from groundwater.mapping.elevation import ElevationGrid, WindowCentre, row_metric
from groundwater.mapping.lineaments import (
    ROSE_BANDS,
    atan2_deg,
    binomial_smooth,
    lineament_candidates,
    lineament_captions,
    lineament_geojson,
    lineament_lonlat,
)
from groundwater.mapping.terrain_analysis import LAND, analyse_terrain
from groundwater.text import phrase

JS = Path(__file__).resolve().parents[1] / "docs" / "js"
LAT0, LON0 = 8.5, -11.5
ARCSEC = 1 / 3600


# ---------------------------------------------------------------------------
# Windows built for the purpose
# ---------------------------------------------------------------------------

def _axes(rows: int, cols: int) -> tuple[np.ndarray, np.ndarray]:
    return LON0 + np.arange(cols) * ARCSEC, LAT0 + np.arange(rows) * ARCSEC


def _frame(rows: int, cols: int, shown) -> tuple[float, float]:
    """The metres a column and a row span in the window's frame, as the
    module takes them: the cell size of the middle row of the square shown."""
    lons, lats = _axes(rows, cols)
    metric = row_metric(lons, lats)
    mid = min((shown[0] + shown[1]) // 2, rows - 1)
    return float(metric.dx[mid]), float(metric.dy[mid])


def _relief(rows: int, cols: int, seed: int, relief: float = 40.0, beta: float = 3.2) -> np.ndarray:
    """Random relief with no preferred direction: noise whose spectrum falls
    off as k^-beta, scaled to ``relief`` metres and lifted above the sea."""
    rng = np.random.default_rng(seed)
    kx = np.fft.fftfreq(cols)
    ky = np.fft.fftfreq(rows)
    k = np.sqrt(kx[None, :] ** 2 + ky[:, None] ** 2)
    k[0, 0] = 1.0
    spectrum = (rng.normal(size=(rows, cols)) + 1j * rng.normal(size=(rows, cols))) * k ** (-beta / 2)
    spectrum[0, 0] = 0.0
    z = np.real(np.fft.ifft2(spectrum))
    return (z - z.min()) / (z.max() - z.min()) * relief + 50.0


def _plant(z: np.ndarray, frame, kind: str, strike: float, centre, length: float, depth: float = 8.0,
           width: float = 90.0, taper: float = 200.0) -> None:
    """Cut a straight valley (or raise a ridge) of Gaussian section into
    ``z``: ``length`` metres along ``strike`` (degrees clockwise from north)
    through ``centre`` ``(x, y)`` in the frame, ``depth`` metres deep at
    its axis and ``width`` the Gaussian's half-width, tapering off over
    ``taper`` metres beyond each end."""
    rows, cols = z.shape
    dx, dy = frame
    yy, xx = np.mgrid[0:rows, 0:cols]
    x = xx * dx
    y = yy * dy
    ux, uy = math.sin(math.radians(strike)), math.cos(math.radians(strike))
    t = (x - centre[0]) * ux + (y - centre[1]) * uy
    d = -(x - centre[0]) * uy + (y - centre[1]) * ux
    profile = np.exp(-(d / width) ** 2) * np.clip(1.0 - (np.abs(t) - length / 2) / taper, 0.0, 1.0)
    z += (-depth if kind == "valley" else depth) * profile


def _analyse(z: np.ndarray, shown=None, cfg: TerrainConfig | None = None, sea_clean: bool = True,
             precision: str = "float64"):
    rows, cols = z.shape
    lons, lats = _axes(rows, cols)
    grid = ElevationGrid(lons=lons, lats=lats, z=np.asarray(z, dtype=np.float64), sea_clean=sea_clean,
                         source_id="copernicus_glo30")
    return analyse_terrain(grid, cfg or TerrainConfig(), shown=shown, precision=precision)


def _found(result, kind: str, strike: float, centre, length: float):
    """The candidate of ``kind`` lying along the planted line: its midpoint
    within 120 m of the line and within the planted span; the longest such."""
    ux, uy = math.sin(math.radians(strike)), math.cos(math.radians(strike))
    best = None
    for item in result.lineaments:
        if item.kind != kind:
            continue
        mx = (item.start[0] + item.end[0]) / 2
        my = (item.start[1] + item.end[1]) / 2
        across = abs(-(mx - centre[0]) * uy + (my - centre[1]) * ux)
        along = abs((mx - centre[0]) * ux + (my - centre[1]) * uy)
        if across < 120.0 and along < length / 2 and (best is None or item.length_m > best.length_m):
            best = item
    return best


def _strike_gap(a: float, b: float) -> float:
    return abs((a - b + 90.0) % 180.0 - 90.0)


# ---------------------------------------------------------------------------
# The arctangent and the smoothing
# ---------------------------------------------------------------------------

def test_atan2_deg_is_atan2_to_a_few_units_in_the_last_place_in_every_quadrant():
    rng = np.random.default_rng(7)
    worst = 0.0
    for _ in range(20000):
        y, x = rng.normal(size=2) * 10.0 ** rng.uniform(-6, 6, 2)
        want = math.degrees(math.atan2(y, x))
        worst = max(worst, abs(atan2_deg(y, x) - want) / max(abs(want), 1e-300))
    assert worst < 1e-15 * 8
    # the axes, the diagonals and the reductions' edges come out exactly or nearly
    assert atan2_deg(0.0, 1.0) == 0.0
    assert atan2_deg(1.0, 0.0) == 90.0
    assert atan2_deg(0.0, -1.0) == 180.0
    assert atan2_deg(-1.0, 0.0) == -90.0
    assert atan2_deg(1.0, 1.0) == pytest.approx(45.0, abs=1e-13)
    assert atan2_deg(math.tan(math.radians(67.5)), 1.0) == pytest.approx(67.5, abs=1e-12)
    assert atan2_deg(0.66, 1.0) == pytest.approx(math.degrees(math.atan(0.66)), abs=1e-13)
    assert atan2_deg(0.0, 0.0) == 0.0
    assert math.isnan(atan2_deg(math.nan, 1.0))
    assert math.isnan(atan2_deg(1.0, math.inf))


def test_binomial_smoothing_keeps_a_plane_and_widens_the_edge_and_a_void_by_a_cell_a_pass():
    rows, cols = 40, 50
    yy, xx = np.mgrid[0:rows, 0:cols]
    plane = 3.0 * yy - 2.0 * xx + 100.0
    for passes in (0, 1, 4):
        out = binomial_smooth(plane, passes)
        inner = out[passes:rows - passes, passes:cols - passes]
        assert np.allclose(inner, plane[passes:rows - passes, passes:cols - passes], rtol=0, atol=1e-11)
        assert np.isnan(out[:passes]).all() and np.isnan(out[:, cols - passes:]).all()
    hole = plane.copy()
    hole[20, 25] = np.nan
    out = binomial_smooth(hole, 3)
    blank = np.isnan(out[3:rows - 3, 3:cols - 3])
    assert int(blank.sum()) == 7 * 7
    assert np.isnan(out[17:24, 22:29]).all()
    assert binomial_smooth(plane, 0) is not plane
    with pytest.raises(ValueError):
        binomial_smooth(plane, -1)
    with pytest.raises(ValueError):
        binomial_smooth(np.zeros(5), 1)


# ---------------------------------------------------------------------------
# What is found
# ---------------------------------------------------------------------------

_PLANTED = (("valley", 30.0, 0.27, 0.27), ("ridge", 120.0, 0.73, 0.27),
            ("valley", 75.0, 0.27, 0.73), ("ridge", 165.0, 0.73, 0.73))


def test_valleys_and_ridges_planted_at_known_strikes_are_found_at_their_strike_and_of_their_kind():
    rows = cols = 360
    shown = (30, 330, 30, 330)
    frame = _frame(rows, cols, shown)
    z = _relief(rows, cols, seed=3)
    width_m = cols * frame[0]
    planted = []
    for kind, strike, fx, fy in _PLANTED:
        centre = (fx * width_m, fy * rows * frame[1])
        _plant(z, frame, kind, strike, centre, 3000.0)
        planted.append((kind, strike, centre))
    result = lineament_candidates(_analyse(z, shown))
    assert result.frame == frame
    for kind, strike, centre in planted:
        item = _found(result, kind, strike, centre, 3000.0)
        assert item is not None, f"the {kind} at {strike} degrees was not found"
        assert _strike_gap(item.strike_deg, strike) < 2.0, (kind, strike, item.strike_deg)
        assert item.length_m > 2000.0, (kind, strike, item.length_m)
        assert 0.0 <= item.strike_deg < 180.0
    # a planted valley is never taken for a ridge, nor the reverse
    for kind, strike, centre in planted:
        other = "ridge" if kind == "valley" else "valley"
        wrong = _found(result, other, strike, centre, 3000.0)
        assert wrong is None or wrong.length_m < 0.5 * _found(result, kind, strike, centre, 3000.0).length_m


@pytest.mark.parametrize("gap_m, linked", [(150.0, True), (900.0, False)])
def test_valleys_that_line_up_across_a_short_gap_are_one_candidate_and_across_a_long_one_two(gap_m, linked):
    rows = cols = 300
    shown = (20, 280, 20, 280)
    frame = _frame(rows, cols, shown)
    z = _relief(rows, cols, seed=11, relief=15.0)
    strike = 50.0
    ux, uy = math.sin(math.radians(strike)), math.cos(math.radians(strike))
    middle = (cols * frame[0] / 2, rows * frame[1] / 2)
    piece = 1300.0
    reach = (piece + gap_m) / 2
    for sign in (-1.0, 1.0):
        centre = (middle[0] + sign * reach * ux, middle[1] + sign * reach * uy)
        _plant(z, frame, "valley", strike, centre, piece, depth=10.0, taper=40.0)
    result = lineament_candidates(_analyse(z, shown))
    along = [item for item in result.lineaments
             if item.kind == "valley" and _strike_gap(item.strike_deg, strike) < 5.0
             and abs(-((item.start[0] + item.end[0]) / 2 - middle[0]) * uy
                     + ((item.start[1] + item.end[1]) / 2 - middle[1]) * ux) < 120.0]
    if linked:
        assert any(item.pieces >= 2 and item.length_m > 2 * piece for item in along), along
    else:
        assert along and all(item.length_m < piece + gap_m / 2 for item in along), along


def test_flat_ground_has_no_candidates_and_its_caption_says_so():
    rows = cols = 120
    lat_ramp = np.add.outer(np.arange(rows) * 0.01, np.zeros(cols)) + 80.0
    result = lineament_candidates(_analyse(lat_ramp, (10, 110, 10, 110)))
    assert result.lineaments == ()
    assert result.rose_valley_m == (0.0,) * ROSE_BANDS and result.rose_ridge_m == (0.0,) * ROSE_BANDS
    captions = lineament_captions(result, "the plain")
    cfg = TerrainConfig()
    assert captions["lineaments"] == phrase(
        "terrain.caption_lineaments_none", length=cfg.lineament_min_length_m, smoothing=cfg.lineament_smoothing_m,
        azimuths="270°, 315°, 0° and 45°")
    meta = _meta()
    text = lineament_geojson(result, *_axes(rows, cols), meta)
    assert json.loads(text)["features"] == []


def test_sea_is_never_a_centreline_and_a_candidate_lies_on_land():
    rows = cols = 260
    shown = (20, 240, 20, 240)
    frame = _frame(rows, cols, shown)
    z = _relief(rows, cols, seed=5, relief=30.0)
    z[:, :90] = 0.0                       # sea along the west edge, joined to it
    _plant(z, frame, "valley", 10.0, (170 * frame[0], 130 * frame[1]), 3000.0)
    analysis = _analyse(z, shown)
    assert (analysis.core.cls[:, :90] != LAND).all()
    result = lineament_candidates(analysis)
    assert result.lineaments
    for item in result.lineaments:
        for f in np.linspace(0.0, 1.0, 21):
            x = item.start[0] + f * (item.end[0] - item.start[0])
            c = round(x / frame[0])
            assert c >= 88, (item, c)          # within a cell or two of the coast at most


def test_a_candidate_across_the_edge_of_the_square_shown_is_cut_to_it():
    rows = cols = 300
    shown = (60, 240, 60, 240)
    frame = _frame(rows, cols, shown)
    z = _relief(rows, cols, seed=9, relief=10.0)
    # a north-south valley from well south of the square to its middle
    centre = (150 * frame[0], 110 * frame[1])
    _plant(z, frame, "valley", 0.0, centre, 3600.0, depth=12.0)
    result = lineament_candidates(_analyse(z, shown))
    item = _found(result, "valley", 0.0, centre, 3600.0)
    assert item is not None and item.cut
    south = (shown[0] - 0.5) * frame[1]
    assert item.start[1] == pytest.approx(south, abs=1e-6)
    assert item.length_m == pytest.approx(item.end[1] - item.start[1], rel=1e-3)
    west, east = (shown[2] - 0.5) * frame[0], (shown[3] - 0.5) * frame[0]
    north = (shown[1] - 0.5) * frame[1]
    for each in result.lineaments:
        for x, y in (each.start, each.end):
            assert west - 1e-6 <= x <= east + 1e-6 and south - 1e-6 <= y <= north + 1e-6


def test_the_rose_adds_up_every_candidate_in_the_band_of_its_strike():
    rows = cols = 360
    shown = (30, 330, 30, 330)
    frame = _frame(rows, cols, shown)
    z = _relief(rows, cols, seed=3)
    for kind, strike, fx, fy in _PLANTED:
        _plant(z, frame, kind, strike, (fx * cols * frame[0], fy * rows * frame[1]), 3000.0)
    result = lineament_candidates(_analyse(z, shown))
    assert result.lineaments
    valley = [0.0] * ROSE_BANDS
    ridge = [0.0] * ROSE_BANDS
    for item in result.lineaments:
        band = int(item.strike_deg // 10)
        (valley if item.kind == "valley" else ridge)[band] += item.length_m
    assert list(result.rose_valley_m) == pytest.approx(valley, rel=1e-12)
    assert list(result.rose_ridge_m) == pytest.approx(ridge, rel=1e-12)
    assert sum(result.rose_valleys) == result.summary["valleys"]
    assert sum(result.rose_ridges) == result.summary["ridges"]
    assert result.summary["candidates"] == len(result.lineaments)
    assert result.summary["length_m"] == pytest.approx(sum(valley) + sum(ridge), rel=1e-12)
    assert [item.id for item in result.lineaments] == list(range(len(result.lineaments)))


@pytest.mark.parametrize("name, value", [
    ("lineament_smoothing_m", 0.0), ("lineament_contrast_km", -1.0), ("lineament_share", 0.0),
    ("lineament_share", 1.5), ("lineament_turn_deg", 90.0), ("lineament_link_angle_deg", math.nan),
    ("lineament_min_length_m", math.inf), ("lineament_piece_m", -300.0),
])
def test_settings_out_of_range_are_refused_by_name(name, value):
    z = _relief(60, 60, seed=1)
    analysis = _analyse(z)
    with pytest.raises(ValueError, match=f"terrain.{name} must be"):
        lineament_candidates(analysis, dataclasses.replace(TerrainConfig(), **{name: value}))


def _meta(notice: str | None = None) -> dict:
    return {"label": "Copernicus GLO-30 tile N08 W012", "figure_credit": "Elevation: the test set.",
            "notice": notice, "surface": phrase("terrain.surface_copernicus"), "radius": 5.0,
            "centre": WindowCentre(-11.47, 8.53, "the test site", True, None)}


def test_the_geojson_and_the_captions_say_what_the_candidates_are():
    rows = cols = 360
    shown = (30, 330, 30, 330)
    frame = _frame(rows, cols, shown)
    z = _relief(rows, cols, seed=3)
    for kind, strike, fx, fy in _PLANTED:
        _plant(z, frame, kind, strike, (fx * cols * frame[0], fy * rows * frame[1]), 3000.0)
    result = lineament_candidates(_analyse(z, shown))
    lons, lats = _axes(rows, cols)
    text = lineament_geojson(result, lons, lats, _meta("The Copernicus notice."))
    data = json.loads(text)
    assert "inferred from terrain, not confirmed by geophysics" in data["description"]
    assert data["notice"] == "The Copernicus notice."
    assert data["min_length_m"] == 600
    assert len(data["features"]) == len(result.lineaments)
    for feature, item in zip(data["features"], result.lineaments, strict=True):
        assert list(feature["properties"]) == ["lineament", "kind", "length_m", "strike_deg", "pieces", "cut"]
        assert feature["properties"]["lineament"] == item.id and feature["properties"]["kind"] == item.kind
        (lon_a, lat_a), (lon_b, lat_b) = feature["geometry"]["coordinates"]
        want = lineament_lonlat(result, lons, lats, item.start)
        assert (lon_a, lat_a) == (round(want[0], 6), round(want[1], 6))
        for lon, lat in ((lon_a, lat_a), (lon_b, lat_b)):
            assert lons[0] <= lon <= lons[-1] and lats[0] <= lat <= lats[-1]
    captions = lineament_captions(result, "the test site")
    assert captions["title_lineaments"] == "Lineament candidates - the test site"
    assert captions["title_rose"] == "Strike of the lineament candidates - the test site"
    assert captions["lineaments"].startswith(
        f"{result.summary['valleys']} straight valley" if result.summary["valleys"] else "0 straight valleys")
    assert "inferred from terrain, not confirmed by geophysics" in captions["lineaments"]
    assert captions["rose"] == phrase("terrain.caption_rose")


@pytest.mark.slow
def test_random_terrain_gives_a_rose_with_no_preferred_direction():
    """On relief with no preferred direction, the candidates' strikes favour
    none: the harmonics of the length-weighted rose with periods of 180, 90
    and 45 degrees stay under 0.1. Edges taken from each hillshade alone
    gave 0.10 at 90 degrees, and straight runs of D8 drainage lines 0.55, so
    either would fail here. Each terrain is also run turned by 90 degrees."""
    lengths = []
    angles = []
    for seed in range(6):
        base = _relief(400, 400, seed=200 + seed, relief=150.0)
        for z in (base, np.rot90(base).copy()):
            result = lineament_candidates(_analyse(z, (30, 370, 30, 370)))
            for item in result.lineaments:
                lengths.append(item.length_m)
                angles.append(math.radians(item.strike_deg))
    weights = np.array(lengths)
    theta = np.array(angles)
    assert weights.size > 300
    for k in (2, 4, 8):
        c = float(np.sum(weights * np.cos(k * theta)) / weights.sum())
        s = float(np.sum(weights * np.sin(k * theta)) / weights.sum())
        assert math.hypot(c, s) < 0.1, (k, c, s)


# ---------------------------------------------------------------------------
# The browser's engine, held to the Python one to the bit
# ---------------------------------------------------------------------------

_DRIVER = r"""
import { readFileSync } from 'node:fs';
import { createInterface } from 'node:readline';
import vm from 'node:vm';
const sandbox = vm.createContext({ console, structuredClone });
for (const f of ['gwt-data.js', 'gwt-core.js']) {
  vm.runInContext(readFileSync(process.argv[2] + '/' + f, 'utf8'), sandbox, { filename: f });
}
const C = sandbox.GWT.core;
const F64 = vm.runInContext('Float64Array', sandbox);
const f64 = (b64) => new F64(new Uint8Array(Buffer.from(b64, 'base64')).buffer);
const hex = (v) => {
  const view = new DataView(new ArrayBuffer(8));
  view.setFloat64(0, Number(v));
  let out = '';
  for (let i = 0; i < 8; i++) out += view.getUint8(i).toString(16).padStart(2, '0');
  return out;
};
const ops = {
  atan(r) { return r.points.map(([y, x]) => hex(C.atan2Deg(y, x))); },
  smooth(r) { return Array.from(C.binomialSmooth(f64(r.z), r.rows, r.cols, r.passes), hex); },
  lineaments(r) {
    const lons = f64(r.lons), lats = f64(r.lats);
    const grid = { lons, lats, z: f64(r.z), rows: r.rows, cols: r.cols, assumedSea: null,
      sourceId: 'copernicus_glo30', seaClean: true, label: 'x' };
    const a = C.analyseTerrain(grid, r.analysed, null, r.precision || 'float64', r.shown);
    const heard = [];
    let result;
    try {
      result = C.lineamentCandidates(a, r.config, (f, label) => heard.push([hex(f), label]));
    } catch (e) {
      return { refused: String(e && e.message) };
    }
    return {
      lineaments: result.lineaments.map((l) => [l.id, l.kind, l.start.map(hex), l.end.map(hex), hex(l.length_m),
        hex(l.strike_deg), l.pieces, l.cells, l.cut]),
      summary: Object.entries(result.summary).map(([k, v]) => [k, k === 'length_m' || k === 'threshold' ? hex(v) : v]),
      roses: [result.roseValleyM.map(hex), result.roseRidgeM.map(hex), result.roseValleys, result.roseRidges],
      frame: result.frame.map(hex), heard,
      captions: C.lineamentCaptions(result, r.where),
      geojson: C.lineamentGeoJson(result, lons, lats, r.meta),
    };
  },
};
for await (const line of createInterface({ input: process.stdin })) {
  const request = JSON.parse(line);
  let answer;
  try {
    answer = { ok: ops[request.op](request) };
  } catch (e) {
    answer = { threw: String(e && e.stack || e) };
  }
  process.stdout.write(JSON.stringify(answer) + '\n');
}
"""


class _Browser:
    """The browser's engine in a Node vm, asked one question at a time."""

    def __init__(self, tmp_path: Path):
        node = shutil.which("node")
        if node is None:
            pytest.skip("node is not installed; run `node --version` to check")
        driver = tmp_path / "lineaments.mjs"
        driver.write_text(_DRIVER, encoding="utf-8")
        self._node = subprocess.Popen([node, str(driver), str(JS)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      text=True, encoding="utf-8")

    def ask(self, op: str, **request):
        assert self._node.stdin is not None and self._node.stdout is not None
        self._node.stdin.write(json.dumps({"op": op, **request}) + "\n")
        self._node.stdin.flush()
        line = self._node.stdout.readline()
        assert line, "the Node driver stopped; its error is above"
        answer = json.loads(line)
        assert "threw" not in answer, answer["threw"]
        return answer["ok"]

    def close(self) -> None:
        assert self._node.stdin is not None
        self._node.stdin.close()
        self._node.wait(timeout=60)


@pytest.fixture(scope="module")
def browser(tmp_path_factory):
    engine = _Browser(tmp_path_factory.mktemp("lineaments"))
    yield engine
    engine.close()


def _hex(value) -> str:
    return struct.pack(">d", float(value)).hex()


def _b64(values) -> str:
    import base64

    return base64.b64encode(np.ascontiguousarray(values, dtype="<f8").tobytes()).decode("ascii")


def test_the_browser_arctangent_and_smoothing_are_pythons_to_the_bit(browser):
    rng = np.random.default_rng(13)
    points = [[float(y), float(x)] for y, x in rng.normal(size=(3000, 2)) * 10.0 ** rng.uniform(-8, 8, (3000, 2))]
    points += [[0.0, 0.0], [-0.0, 1.0], [1.0, -0.0], [0.66, 1.0], [2.41421356237309504880, 1.0],
               [1e-300, 1.0], [1.0, 1e-300], [-1.0, -1.0], [3.0, -4.0]]
    assert browser.ask("atan", points=points) == [_hex(atan2_deg(y, x)) for y, x in points]
    z = rng.normal(size=(23, 31)) * 40.0
    z[5, 7] = np.nan
    z[17, 3:9] = np.nan
    for passes in (0, 1, 2, 7):
        want = [_hex(v) for v in binomial_smooth(z, passes).ravel()]
        assert browser.ask("smooth", z=_b64(z), rows=23, cols=31, passes=passes) == want, passes


def _window_case(seed: int) -> dict:
    """A seeded window: random relief with planted valleys and ridges, and
    by turns voids, sea, a thin grid, an offset square, settings at the
    edges of their ranges and the apps' float32 analysis, whose layers the
    candidates do not read."""
    rng = np.random.default_rng(1000 + seed)
    shape = [(140, 160), (200, 180), (90, 260), (3, 80), (160, 140), (120, 120), (220, 200), (150, 170)][seed % 8]
    rows, cols = shape
    margin = 0 if seed % 4 == 3 else int(rng.integers(5, 25))
    shown = (margin, rows - margin, margin + int(rng.integers(0, 5)), cols - margin)
    z = _relief(rows, cols, seed=seed, relief=float(rng.uniform(10, 120)))
    if rows >= 3:
        frame = _frame(rows, cols, shown)
        for _ in range(int(rng.integers(1, 4))):
            kind = "valley" if rng.random() < 0.5 else "ridge"
            centre = (float(rng.uniform(0.2, 0.8)) * cols * frame[0], float(rng.uniform(0.2, 0.8)) * rows * frame[1])
            _plant(z, frame, kind, float(rng.uniform(0, 180)), centre, float(rng.uniform(800, 3000)),
                   depth=float(rng.uniform(3, 12)))
    if seed % 3 == 1:
        r0, c0 = int(rng.integers(0, rows - 2)), int(rng.integers(0, cols - 10))
        z[r0:r0 + 6, c0:c0 + 9] = np.nan          # a void
    if seed % 5 == 2:
        z[:, : cols // 5] = 0.0                    # sea along the west edge
    settings = {}
    if seed % 6 == 5:
        settings = {"lineament_share": 1.0, "lineament_smoothing_m": 20.0, "lineament_contrast_km": 0.3,
                    "lineament_min_length_m": 200.0, "lineament_piece_m": 120.0, "lineament_link_gap_m": 900.0,
                    "lineament_link_angle_deg": 25.0}
    elif seed % 6 == 2:
        settings = {"lineament_share": 0.1, "lineament_smoothing_m": 120.0, "lineament_straight_m": 30.0}
    return {"z": z, "shown": shown, "settings": settings, "precision": "float32" if seed % 4 == 1 else "float64"}


def _python_answer(case: dict) -> dict:
    z, shown = case["z"], case["shown"]
    rows, cols = z.shape
    cfg = dataclasses.replace(TerrainConfig(), **case["settings"])
    analysis = _analyse(z, shown, precision=case.get("precision", "float64"))
    heard = []
    try:
        result = lineament_candidates(analysis, cfg, lambda f, label: heard.append([_hex(f), label]))
    except ValueError as exc:
        return {"refused": str(exc)}
    lons, lats = _axes(rows, cols)
    return {
        "lineaments": [[item.id, item.kind, [_hex(v) for v in item.start], [_hex(v) for v in item.end],
                        _hex(item.length_m), _hex(item.strike_deg), item.pieces, item.cells, item.cut]
                       for item in result.lineaments],
        "summary": [[k, _hex(v) if k in ("length_m", "threshold") else v] for k, v in result.summary.items()],
        "roses": [[_hex(v) for v in result.rose_valley_m], [_hex(v) for v in result.rose_ridge_m],
                  list(result.rose_valleys), list(result.rose_ridges)],
        "frame": [_hex(v) for v in result.frame], "heard": heard,
        "captions": lineament_captions(result, "the test site"),
        "geojson": lineament_geojson(result, lons, lats, _meta()),
    }


def _browser_meta() -> dict:
    meta = _meta()
    centre = meta["centre"]
    meta["centre"] = {"lon": centre.lon, "lat": centre.lat, "label": centre.label}
    return meta


@pytest.mark.parametrize("seed", range(16))
def test_the_browser_finds_the_same_candidates_to_the_bit(browser, seed):
    case = _window_case(seed)
    z = case["z"]
    rows, cols = z.shape
    lons, lats = _axes(rows, cols)
    js = browser.ask("lineaments", z=_b64(z), lons=_b64(lons), lats=_b64(lats), rows=rows, cols=cols,
                     shown=list(case["shown"]), analysed=None, precision=case["precision"],
                     config={"terrain": case["settings"]} if case["settings"] else None,
                     where="the test site", meta=_browser_meta())
    py = _python_answer(case)
    assert js == py
    if seed in (0, 1, 6):
        assert py["lineaments"], "a window with planted features found none"


def test_the_browser_refuses_the_settings_python_refuses_in_its_words(browser):
    z = _relief(40, 40, seed=2)
    lons, lats = _axes(40, 40)
    for name, value in [("lineament_share", 0.0), ("lineament_turn_deg", 95.0), ("lineament_link_gap_m", -1.0)]:
        case = {"z": z, "shown": (0, 40, 0, 40), "settings": {name: value}}
        js = browser.ask("lineaments", z=_b64(z), lons=_b64(lons), lats=_b64(lats), rows=40, cols=40,
                         shown=[0, 40, 0, 40], analysed=None, config={"terrain": {name: value}},
                         where="x", meta=_browser_meta())
        assert js == _python_answer(case) == {"refused": js["refused"]}
        assert js["refused"].startswith(f"terrain.{name} must be")

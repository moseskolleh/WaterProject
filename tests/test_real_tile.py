"""The real-tile acceptance: a whole Copernicus GLO-30 tile, read by the
toolkit's own reader and held to GDAL, then read as the apps read it and
analysed at the default window (PLAN.md step 4.1).

The committed fixtures are clips of a few dozen cells a side, built by the
project's own scripts. A tile as Copernicus publishes it is 3600 by 3600
cells of DEFLATE with the floating-point predictor, in blocks of 1024 by
1024, and none of the fixtures is the size of one of its blocks. This runs
the readers and the analysis on one. It is local and never in CI: a tile is
48 MB, and none is committed (.gitignore keeps any under tests/acceptance/
out). Every test is skipped unless GWT_DEM_TILE names a tile:

    GWT_DEM_TILE=path/to/n08w012.tif python -m pytest -rP tests/test_real_tile.py
    GWT_DEM_TILE=path/to/n08w012.tif node tests/webapp/realtile.mjs

A variable that is set but names no file, or a file not laid out as a
GLO-30 tile, fails rather than skips: setting it is asking for the run, and
a mistyped path must not read as a pass. The tile may be named as
Copernicus names it or renamed (the copy the design measured is
n08w012.tif); the checks of the credit read it under both kinds of name
whatever it is called. -rP prints what each test measured.

The last test writes tests/acceptance/real_tile.json: what the browser must
reproduce. tests/webapp/realtile.mjs reads the same tile in Chromium,
through the browser's engine, and holds its whole-tile digest, its reads of
the window, the layers' digests, the drainage lines and their parts, the
captions and the GeoJSON to it.

GDAL, through rasterio, is the oracle for the values and the cell centres,
as in test_geotiff.py; the two tests that need it skip without it.
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import json
import math
import os
import re
import struct
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from groundwater.config import TerrainConfig
from groundwater.geotiff import GeoTiffError, block_ranges, decode_block, open_geotiff, read_geotiff
from groundwater.mapping.elevation import (
    elevation_label_and_credit,
    file_notes,
    open_elevation_file,
    plan_window,
    read_elevation,
    read_window,
    window_centre,
)
from groundwater.mapping.terrain_analysis import LAND, SEA, analyse_terrain, drainage_geojson, terrain_captions
from groundwater.text import phrase

TILE = os.environ.get("GWT_DEM_TILE", "")
OUT = Path(__file__).resolve().parent / "acceptance" / "real_tile.json"
ARCSEC = 1 / 3600

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(not TILE, reason="GWT_DEM_TILE names no Copernicus GLO-30 tile to read"),
]

# The neighbour order K (E, S, W, N, SE, SW, NW, NE) and its ESRI codes,
# written out again here, as test_terrain_analysis.py writes them
DR = (0, -1, 0, 1, -1, -1, 1, 1)
DC = (1, 0, -1, 0, 1, -1, -1, 1)
ESRI = (1, 4, 16, 64, 2, 8, 32, 128)


@pytest.fixture
def rasterio():
    return pytest.importorskip("rasterio")


# ---------------------------------------------------------------------------
# The tile, and the windows read from it
# ---------------------------------------------------------------------------

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@contextlib.contextmanager
def _recorded(path: Path):
    """``read_at(offset, length)`` on the file, and the list of the reads
    it made, so that a test can say what a window cost."""
    reads: list[tuple[int, int]] = []
    with path.open("rb") as handle:

        def read_at(offset: int, length: int) -> bytes:
            reads.append((offset, length))
            handle.seek(offset)
            return handle.read(length)

        yield read_at, reads


def _names(layout) -> tuple[str, str, str]:
    """The tile's code ("N08 W012"), the name Copernicus gives it, and a
    bare name such as the scratch copy has (n08w012.tif)."""
    lon0, lat0 = math.floor(layout.x0 + 0.5), math.floor(layout.y0 + 0.5) - 1
    ns, ew = ("N" if lat0 >= 0 else "S"), ("E" if lon0 >= 0 else "W")
    code = f"{ns}{abs(lat0):02d} {ew}{abs(lon0):03d}"
    copernicus = f"Copernicus_DSM_COG_10_{ns}{abs(lat0):02d}_00_{ew}{abs(lon0):03d}_00_DEM.tif"
    return code, copernicus, code.replace(" ", "").lower() + ".tif"


@pytest.fixture(scope="module")
def tile():
    """The tile named by GWT_DEM_TILE: its layout, read whole, and the names
    to read it under. Fails on a variable that names no GLO-30 tile."""
    path = Path(TILE)
    if not path.is_file():
        pytest.fail(f"GWT_DEM_TILE names {TILE}, which is not a file")
    refusal = None
    with _recorded(path) as (read_at, _):
        try:
            layout = open_geotiff(path.name, path.stat().st_size, read_at)
        except GeoTiffError as error:
            refusal = str(error)
    if refusal is not None:
        pytest.fail(f"GWT_DEM_TILE names {path.name}, which the reader refuses: {refusal}")
    wanted = {
        "in EPSG 4326": layout.model_type == 2 and layout.epsg == 4326,
        "at one arc-second": abs(layout.sx - ARCSEC) <= 1e-12 and abs(layout.sy - ARCSEC) <= 1e-12,
        "of 3600 by 3600 cells": (layout.width, layout.height) == (3600, 3600),
        "PixelIsPoint on whole degrees": layout.raster_type == 2
        and abs(layout.x0 - round(layout.x0)) <= 1e-9 and abs(layout.y0 - round(layout.y0)) <= 1e-9,
        "of float32 samples": (layout.sample_format, layout.bits) == (3, 32),
    }
    unmet = [what for what, met in wanted.items() if not met]
    if unmet:
        pytest.fail(f"GWT_DEM_TILE names {path.name}, which is not laid out as a Copernicus GLO-30 tile "
                    f"(not {', not '.join(unmet)})")
    start = time.perf_counter()
    raster = read_geotiff(path)
    seconds = time.perf_counter() - start
    code, copernicus, bare = _names(layout)
    return SimpleNamespace(path=path, name=path.name, size=path.stat().st_size, sha256=_sha256(path),
                           layout=raster.layout, raster=raster, seconds=seconds, code=code,
                           copernicus=copernicus, bare=bare)


def _read(tile, name: str, declared: tuple[str, str] = ("detect", "")) -> SimpleNamespace:
    """The default window around the middle of the tile, read under
    ``name`` as read_elevation reads it, step by step so that the reads it
    makes are recorded: the file opened for its layout, the window centred
    with no site, planned at the default radius and margin, and read."""
    cfg = TerrainConfig()
    with _recorded(tile.path) as (read_at, reads):
        found = open_elevation_file(name, tile.size, read_at)
        opening = list(reads)
        centre = window_centre(None, [found])
        plan = plan_window([found], centre, cfg.analysis_radius_km, cfg, declared=declared)
        start = time.perf_counter()
        read = read_window(plan, {name: read_at}, cfg)
        seconds = time.perf_counter() - start
        window = reads[len(opening):]
    return SimpleNamespace(name=name, declared=declared, found=found, centre=centre, plan=plan, read=read,
                           opening=opening, window=window, seconds=seconds)


@pytest.fixture(scope="module")
def windows(tile):
    """The window read under the tile's own name, under the name Copernicus
    gives it, under a bare name, and under the bare name declared as
    Copernicus GLO-30."""
    out = {"own": _read(tile, tile.name), "copernicus": _read(tile, tile.copernicus)}
    out["renamed"] = out["own"] if tile.name == tile.bare else _read(tile, tile.bare)
    out["declared"] = _read(tile, tile.bare, ("copernicus_glo30", ""))
    return out


def _meta(read, a) -> dict:
    """What drainage_geojson is told about a window read with
    read_elevation, as an app tells it (test_terrain_analysis's _read_meta)."""
    return {"label": read.grid.source, "figure_credit": read.figure_credit, "notice": read.notice,
            "surface": read.surface, "area": a.settings.drainage_area_km2, "radius": read.plan.radius_km,
            "margin": read.plan.margin_km, "centre": read.centre, "fill_note_m": a.settings.fill_note_m,
            "sea_clean": read.grid.sea_clean, "sea_cells": int(np.count_nonzero(a.core.cls == SEA)),
            "sea_level_m": a.settings.sea_level_m}


@pytest.fixture(scope="module")
def analysis(windows):
    """The window read under the tile's own name, analysed as the apps
    analyse it: the default settings and precision, the square shown cut
    out of the margin."""
    read = windows["own"].read
    start = time.perf_counter()
    a = analyse_terrain(read.grid, TerrainConfig(), assumed_sea=read.assumed_sea, shown=read.shown)
    seconds = time.perf_counter() - start
    return SimpleNamespace(a=a, seconds=seconds, captions=terrain_captions(a, read, read.centre.label),
                           geojson=drainage_geojson(a.core, a.parts, _meta(read, a)))


# ---------------------------------------------------------------------------
# The tile read whole
# ---------------------------------------------------------------------------

def test_every_value_of_the_tile_is_what_gdal_reads_to_the_bit(tile, rasterio):
    """Prevents a decoder that is right on clips of a few dozen cells and
    wrong on a tile as published: DEFLATE streams of about 3 MB each, the
    floating-point predictor across rows of 1024 samples, and the edge
    blocks padded past the 3600th row and column. Every one of the
    12,960,000 values is GDAL's to the bit (once a -0 is read as +0), and
    a cell is void exactly where GDAL has no value."""
    with rasterio.open(tile.path) as dataset:
        band = dataset.read(1, masked=False)
        nodata = dataset.nodata
    z = tile.raster.z[::-1]
    assert band.dtype == np.float32 and band.shape == z.shape == (3600, 3600)
    gdal = band.astype(np.float64) + 0.0
    kept = ~np.isnan(z)
    assert np.array_equal(z[kept].view(np.uint64), gdal[kept].view(np.uint64))
    gdal_void = np.isnan(band) if nodata is None else np.isnan(band) | (band == nodata)
    assert np.array_equal(~kept, gdal_void)
    negative_zero = int(np.count_nonzero((band == 0) & np.signbit(band)))
    print(f"{band.size:,} values read in {tile.seconds:.2f} s, every one GDAL {rasterio.__gdal_version__}'s "
          f"to the bit; {int(np.count_nonzero(~kept)):,} void, {negative_zero} stored as -0; heights "
          f"{np.nanmin(z):.2f} to {np.nanmax(z):.2f} m")


def test_the_tile_is_centred_on_its_tie_point_and_every_centre_is_gdals_within_1e_12_degree(tile, rasterio):
    """Prevents the half-cell shift a PixelIsPoint tile invites: the tile's
    first centre is its tie point, a whole degree (-12.0 and 9.0 for N08
    W012), where GDAL puts the corner of its cell half a cell further out
    (-12.000138889). Every column and row centre is GDAL's within 1e-12
    degree, not to the bit, because GDAL computes (X - 0.5*Sx) + (i +
    0.5)*Sx where both engines compute x0 + i*Sx."""
    layout, raster = tile.layout, tile.raster
    with rasterio.open(tile.path) as dataset:
        t = dataset.transform
        epsg = dataset.crs.to_epsg()
        point = dataset.tags().get("AREA_OR_POINT")
    assert epsg == 4326 and point == "Point" and layout.raster_type == 2
    assert layout.x0 == math.floor(layout.x0) and layout.y0 == math.floor(layout.y0)
    assert abs(t.c - (layout.x0 - 0.5 * layout.sx)) <= 1e-12 and abs(t.f - (layout.y0 + 0.5 * layout.sy)) <= 1e-12
    gdal_x = t.c + (np.arange(layout.width) + 0.5) * t.a
    gdal_y = t.f + (np.arange(layout.height - 1, -1, -1) + 0.5) * t.e
    worst_x, worst_y = float(np.abs(gdal_x - raster.x).max()), float(np.abs(gdal_y - raster.y).max())
    assert worst_x <= 1e-12 and worst_y <= 1e-12
    assert raster.x[0] == layout.x0 and raster.y[-1] == layout.y0
    print(f"first centre {layout.x0!r}, {layout.y0!r}; GDAL's origin {t.c!r}, {t.f!r}; "
          f"{int(np.count_nonzero(gdal_x != raster.x))} of {layout.width} column centres and "
          f"{int(np.count_nonzero(gdal_y != raster.y))} of {layout.height} row centres differ from GDAL's "
          f"in the last bits, at most {worst_x:.2g} and {worst_y:.2g} degree")


def test_every_block_of_the_tile_decodes_with_no_void_and_no_implausible_height(tile):
    """Prevents a block that only a whole-tile read would reach failing
    unseen: each of the tile's blocks, the padded ones on its east and
    south edges included, is read on its own as a window reads it and
    decodes, with every height plausible ground: GLO-30 is filled, so no
    cell of it is void."""
    layout, cfg = tile.layout, TerrainConfig()
    ranges = block_ranges(layout, 0, layout.height, 0, layout.width)
    assert [index for index, *_ in ranges] == list(range(len(layout.offsets)))
    bounds = (cfg.implausible_below_m, cfg.implausible_above_m)
    cells = voids = implausible = 0
    with tile.path.open("rb") as handle:
        for index, offset, length, rows in ranges:
            assert length > 0, f"block {index + 1} is sparse"
            handle.seek(offset)
            values, reasons = decode_block(layout, index, handle.read(length), rows, bounds)
            cells += values.size
            voids += int(np.count_nonzero(reasons == 1))
            implausible += int(np.count_nonzero(reasons == 2))
    assert cells == layout.width * layout.height and voids == implausible == 0
    print(f"{len(ranges)} blocks of {layout.block_width} by {layout.block_height} (compression "
          f"{layout.compression}, predictor {layout.predictor}), {sum(r[2] for r in ranges):,} bytes "
          f"of {tile.size:,}: every one decoded, {voids} void and {implausible} implausible cells")


# ---------------------------------------------------------------------------
# The window the apps read, and its analysis
# ---------------------------------------------------------------------------

def test_a_window_read_as_the_apps_read_it_is_the_whole_reads_slice(tile, windows):
    """Prevents a window that is shifted, flipped or stitched wrongly from
    the blocks it meets: the default window around the middle of the tile,
    read block by block from a few of the file's bytes, holds exactly the
    heights and the cell centres of the same cells of the tile read whole,
    and read_elevation, which the apps call, reads the same."""
    own = windows["own"]
    read, plan, whole = own.read, own.plan, tile.raster
    i, j = plan.ci - plan.hx, tile.layout.height - 1 - (plan.cj + plan.hy)
    assert read.grid.z.shape == (plan.height, plan.width)
    expected = np.ascontiguousarray(whole.z[j:j + plan.height, i:i + plan.width])
    assert np.array_equal(read.grid.z.view(np.uint64), expected.view(np.uint64))
    assert np.array_equal(read.grid.lons.view(np.uint64), whole.x[i:i + plan.width].view(np.uint64))
    assert np.array_equal(read.grid.lats.view(np.uint64), whole.y[j:j + plan.height].view(np.uint64))
    assert read.reasons is not None and not read.reasons.any() and not read.assumed_sea.any()
    assert (read.voids, read.uncovered, read.implausible, read.assumed, read.coverage) == (0, 0, 0, 0, 1.0)
    again = read_elevation([(own.name, tile.path)])
    assert np.array_equal(again.grid.z.view(np.uint64), read.grid.z.view(np.uint64))
    assert again.notes == read.notes and again.figure_credit == read.figure_credit
    r0, r1, c0, c1 = read.shown
    print(f"{plan.height} by {plan.width} cells ({read.cells:,}) around {read.centre.label}, the square shown "
          f"{r1 - r0} by {c1 - c0} ({(r1 - r0) * (c1 - c0):,}); {len(plan.blocks)} of {len(tile.layout.offsets)} "
          f"blocks, {sum(n for _, n in own.window):,} bytes in {len(own.window)} reads after "
          f"{sum(n for _, n in own.opening):,} to open the file, read in {own.seconds:.2f} s; "
          f"equal to the whole read's slice at rows {j}:{j + plan.height}, columns {i}:{i + plan.width}")


def test_the_default_window_resolves_every_flat_and_accounts_for_every_cell_of_area(windows, analysis):
    """Prevents a flat left without a direction, or area lost or counted
    twice, on real ground rather than on a made-up grid: every land cell of
    the 0.96 million has a direction, every one drains to exactly one end,
    each holds itself plus exactly what drains into it, and the ends
    between them hold all the land. The share of the drainage-line cells
    routed across flats or filled hollows, which the figures draw paler,
    is the summary's and is reported."""
    a = analysis.a
    core = a.core
    rows, cols = core.rows, core.cols
    land = core.cls == LAND
    assert a.unresolved == 0 and a.summary["unresolved"] == 0
    assert np.isin(core.code[land], ESRI + (255,)).all()

    # the land cell each land cell drains to, or none: an end
    k_of = np.full(256, -1)
    k_of[list(ESRI)] = np.arange(8)
    r, c = np.nonzero(land)
    k = k_of[core.code[r, c]]
    rr, cc = r + np.take(DR, k), c + np.take(DC, k)
    flows = (k >= 0) & (rr >= 0) & (rr < rows) & (cc >= 0) & (cc < cols)
    flows[flows] = land[rr[flows], cc[flows]]
    cell, into = r * cols + c, rr * cols + cc
    count, area = core.count.ravel(), core.area_units.ravel()
    own_area = np.broadcast_to(a.metric.au_row.astype(np.int64)[:, None], (rows, cols)).ravel()
    inflow_count = np.zeros(rows * cols, dtype=np.int64)
    inflow_area = np.zeros(rows * cols, dtype=np.int64)
    np.add.at(inflow_count, into[flows], count[cell[flows]])
    np.add.at(inflow_area, into[flows], area[cell[flows]])
    assert (count[cell] == 1 + inflow_count[cell]).all()
    assert (area[cell] == own_area[cell] + inflow_area[cell]).all()
    ends = cell[~flows]
    assert int(count[ends].sum()) == cell.size
    assert int(area[ends].sum()) == int(own_area[cell].sum())
    assert not count[~land.ravel()].any() and not area[~land.ravel()].any()

    r0, r1, c0, c1 = core.shown
    stream = a.stream[r0:r1, c0:c1]
    n_stream = int(np.count_nonzero(stream))
    n_flat = int(np.count_nonzero(stream & core.flat_routed[r0:r1, c0:c1]))
    summary = a.summary
    assert (summary["stream"], summary["flat_routed_stream"]) == (n_stream, n_flat)
    assert summary["flat_routed_lines_pct"] == (100.0 * n_flat) / n_stream
    print(f"{rows * cols:,} cells analysed in {analysis.seconds:.2f} s, {cell.size:,} of them land: "
          f"0 unresolved, {ends.size:,} ends holding all {int(own_area[cell].sum()) / 1e8:,.4f} km2 of land; "
          f"{n_flat:,} of the {n_stream:,} drainage-line cells shown ({summary['flat_routed_lines_pct']:.1f}%) "
          f"routed across flats or filled hollows, {summary['contaminated_pct']:.1f}% uncertain, "
          f"{summary['raised_pct']:.1f}% of the land raised by {a.settings.fill_note_m:g} m or more "
          f"(deepest {summary['max_fill_m']:.2f} m); {len(a.links)} drainage lines, {len(a.parts)} parts shown")


def test_the_tile_is_credited_only_under_a_copernicus_name_and_otherwise_prompts_for_its_source(tile, windows):
    """Prevents a renamed tile from being credited to Copernicus on its
    looks alone, and a Copernicus tile from going out without the credit
    and the liability notice its licence asks for. Named as Copernicus
    names it, the tile is credited, with no prompt; renamed, it is a file
    of unstated source, with the bare credit line and the prompt to declare
    it; declared as Copernicus GLO-30, it is credited, and the prompt has
    done its work. The heights are the same whatever the name."""
    copernicus = phrase("terrain.credit_copernicus_modified")
    liability = phrase("terrain.copernicus_liability")
    expected = {
        "copernicus": ("copernicus_glo30", (), phrase("terrain.label_copernicus", n=1, tiles=tile.code),
                       copernicus, liability, "terrain.surface_copernicus", True, ()),
        "renamed": ("unidentified", ("terrain.looks_copernicus",),
                    phrase("terrain.label_unidentified", files=tile.bare), "", None, "terrain.surface_unknown",
                    False, (phrase("terrain.looks_copernicus", file=tile.bare),)),
        "declared": ("unidentified", ("terrain.looks_copernicus",),
                     phrase("terrain.label_declared", declared="Copernicus GLO-30", files=tile.bare),
                     copernicus, liability, "terrain.surface_copernicus", True, ()),
    }
    for kind, (source, notes, label, credit, notice, surface, sea_clean, prompts) in expected.items():
        window = windows[kind]
        read = window.read
        assert (window.found.source_id, window.found.notes) == (source, notes), kind
        assert elevation_label_and_credit([window.found], window.declared)[:3] == (label, credit, notice), kind
        assert (read.grid.source, read.grid.credit, read.notice) == (label, credit, notice), kind
        assert read.surface == phrase(surface) and read.notes[-1] == phrase(surface), kind
        assert read.grid.sea_clean is sea_clean and read.prompts == prompts, kind
        assert file_notes(window.found, window.declared) == prompts, kind
        dx, dy = window.plan.dx, window.plan.dy
        line = (phrase("terrain.figure_credit", label=label, credit=credit, dx=dx, dy=dy) if credit
                else phrase("terrain.figure_credit_bare", label=label, dx=dx, dy=dy))
        assert read.figure_credit == line, kind
        assert np.array_equal(read.grid.z.view(np.uint64), windows["own"].read.grid.z.view(np.uint64)), kind
    own = windows["own"].read
    named = re.match(r"^Copernicus_DSM_(?:COG_)?10_[NS]\d{2}_00_[EW]\d{3}_00_DEM$", tile.path.stem, re.I)
    assert bool(own.grid.credit) is bool(named)
    for kind in expected:
        read = windows[kind].read
        print(f"{kind} ({windows[kind].name}{', declared' if kind == 'declared' else ''}): "
              f"{read.figure_credit} Notice: {'yes' if read.notice else 'none'}. "
              f"Prompts: {' '.join(read.prompts) or 'none'}")


# ---------------------------------------------------------------------------
# What the browser must reproduce
# ---------------------------------------------------------------------------

def _digest(values) -> str:
    """SHA-256 of float64 little-endian values, every NaN 0x7FF8000000000000
    and the signs of zero kept, layers of whole numbers widened: the digest
    parity.mjs takes with C.sha256Hex and make_reference.py with hashlib."""
    a = np.array(values, dtype="<f8").ravel()
    a[np.isnan(a)] = np.nan
    return hashlib.sha256(a.tobytes()).hexdigest()


def _number(value):
    """A number as JSON can carry it: NaN as null, the infinities and -0 as
    strings, as reference.json carries them."""
    value = float(value)
    if value != value:
        return None
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    if value == 0 and math.copysign(1.0, value) < 0:
        return "-0"
    return value


def _spots(values, n: int = 10) -> list:
    v = np.ravel(np.asarray(values, dtype=np.float64))
    return [_number(v[k * (v.size - 1) // (n - 1)]) for k in range(n)]


def _camel(key: str) -> str:
    return re.sub(r"_([a-z])", lambda m: m.group(1).upper(), key)


def _clean(value):
    """Tuples as lists and numpy scalars as numbers, all the way down."""
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return _number(value)
    if isinstance(value, (list, tuple, np.ndarray)):
        return [_clean(v) for v in value]
    return value


def _window_record(window) -> dict:
    """One window's read as realtile.mjs builds its answer from the
    browser's: the file, the set's credit, the prompts, the centre, the
    plan, the reads made, and the read itself."""
    found, plan, read, declared = window.found, window.plan, window.read, window.declared
    label, credit, notice, surface, sea_clean = elevation_label_and_credit([found], declared)
    grid = read.grid
    return {
        "name": window.name, "declared": list(declared),
        "file": [found.source_id, list(found.notes)],
        "credit": [label, credit, notice, surface, sea_clean],
        "prompts": [list(file_notes(found, declared))],
        "centre": [_number(window.centre.lon), _number(window.centre.lat), window.centre.label,
                   window.centre.exact, window.centre.note],
        "plan": {
            "order": [f.name for f in plan.files], "sources": list(plan.sources), "offsets": _clean(plan.offsets),
            "at": [plan.ci, plan.cj, plan.hx, plan.hy, plan.hxs, plan.hys, plan.width, plan.height, plan.tile],
            "dx": _number(plan.dx), "dy": _number(plan.dy),
            "lons": [_digest(plan.lons), _number(plan.lons[0]), _number(plan.lons[-1])],
            "lats": [_digest(plan.lats), _number(plan.lats[0]), _number(plan.lats[-1])],
            "missing": _clean(plan.missing), "edges": [[e.missing, e.file, e.row, e.column] for e in plan.edges],
            "blocks": [[b.file, b.index, b.offset, b.length, _clean(b.rows), b.window, list(b.edges)]
                       for b in plan.blocks],
        },
        "opening": _clean(window.opening),
        "reads": [[window.name, offset, length] for offset, length in window.window],
        "read": {
            "z": [_digest(grid.z), _spots(grid.z)], "reasons": _digest(read.reasons), "sea": _digest(read.assumed_sea),
            "counts": [read.cells, read.voids, read.uncovered, read.implausible, read.assumed],
            "coverage": _number(read.coverage), "shown": list(read.shown), "notes": list(read.notes),
            "prompts": list(read.prompts), "figure": read.figure_credit, "cell": grid.resolution_note,
            "source": grid.source_id, "label": grid.source, "gridCredit": grid.credit, "notice": read.notice,
            "surface": read.surface, "seaClean": grid.sea_clean, "files": list(grid.files),
        },
    }


def _lines(lines) -> list:
    """Links or parts, each the values of its fields in their order."""
    return [_clean(list(dataclasses.astuple(line))) for line in lines]


def _lines_digest(lines) -> str:
    """SHA-256 of the links or parts as one line of JSON, each length by
    its float64 bits: make_reference.py's _ta_lines_digest, which
    parity.mjs takes again in the browser."""
    text = json.dumps([{**dataclasses.asdict(line), "length_m": struct.pack(">d", line.length_m).hex()}
                       for line in lines], separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _analysis_record(analysis) -> dict:
    """The analysis as realtile.mjs builds its answer from the browser's:
    every layer by digest and ten cells, all but the wetness index exact;
    the wetness index, which passes through a library's logarithm, by its
    digest (reported), 50 cells, its count, least and greatest and its
    display range; the summary, the drainage lines and their parts in full,
    the captions and the GeoJSON."""
    a = analysis.a
    core = a.core
    layers = {"cls": core.cls, "code": core.code, "flag": core.flag, "raised": core.raised,
              "flatRouted": core.flat_routed, "stream": a.stream, "count": core.count,
              "areaUnits": core.area_units, "filled": a.filled, "fillDepth": a.fill_depth, "p": a.p, "q": a.q,
              "tanb": a.tanb}
    layers.update({f"hillshade{j}": layer for j, layer in enumerate(a.hillshades)})
    layers.update({"hillshadeMulti": a.hillshade_multi, "twiArg": a.twi_arg, "profile": a.profile,
                   "tangential": a.tangential, "dx": core.dx, "dy": core.dy, "dg": core.dg})
    twi = np.ravel(np.asarray(a.twi, dtype=np.float64))
    finite = np.flatnonzero(np.isfinite(twi))
    at = sorted({int(finite[k * (finite.size - 1) // 49]) for k in range(50)})
    summary = {key: value for key, value in a.summary.items() if key != "twi_range"}
    return {
        "precision": str(np.asarray(a.twi).dtype),
        "layers": {name: [_digest(layer), _spots(layer)] for name, layer in layers.items()},
        "twi": {"digest": _digest(twi), "at": at, "values": [float(twi[i]) for i in at], "count": int(finite.size),
                "min": float(twi[finite].min()), "max": float(twi[finite].max()),
                "range": _clean(a.summary["twi_range"])},
        "summary": {"keys": list(summary), "values": _clean(list(summary.values()))},
        "scalars": [a.unresolved, a.k_cells, a.floored, a.zero_fill], "shown": list(core.shown),
        "fields": {"links": [f.name for f in dataclasses.fields(a.links[0])],
                   "parts": [f.name for f in dataclasses.fields(a.parts[0])]},
        "links": {"digest": _lines_digest(a.links), "values": _lines(a.links)},
        "parts": {"digest": _lines_digest(a.parts), "values": _lines(a.parts)},
        "captions": [list(item) for item in analysis.captions.items()],
        "geojson": analysis.geojson,
    }


def test_what_the_browser_must_reproduce_is_written_for_realtile_mjs(tile, windows, analysis):
    """Prevents realtile.mjs from comparing the browser with a stale run or
    another tile: the file names the tile by its size and SHA-256, and
    holds what this run measured on it, the GeoJSON among it, which must
    parse and hold one feature for each part shown."""
    raster, layout = tile.raster, tile.layout
    doc = json.loads(analysis.geojson)
    assert len(doc["features"]) == len(analysis.a.parts) and doc["attribution"] == windows["own"].read.figure_credit
    record = {
        "tile": {"name": tile.name, "size": tile.size, "sha256": tile.sha256},
        "settings": _clean(dataclasses.asdict(TerrainConfig())),
        "whole": {
            "layout": {_camel(key): _clean(value) for key, value in dataclasses.asdict(layout).items()},
            "z": [_digest(raster.z), _spots(raster.z)], "x": _digest(raster.x), "y": _digest(raster.y),
        },
        "windows": {kind: _window_record(window) for kind, window in windows.items()},
        "analysis": _analysis_record(analysis),
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(record, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes) for {tile.name}, SHA-256 {tile.sha256[:16]}...")

"""The elevation layer: GeoTIFF and .hgt files joined into one window.

mapping/elevation.py turns the raw reader's files into the window the
terrain analysis reads: WGS 84 longitude and latitude only, tiles joined
on one lattice and never resampled, implausible heights voided and
counted, a missing tile taken as sea only when the full edges beside it
are sea, the source credited only when the name and the georeferencing
agree, and the window planned with its margin and its cap. The browser's
elevation layer does the same arithmetic; the parity suite holds the two
together, and these tests hold the Python one to the rules.

The committed fixtures (tests/webapp/fixtures/dem, described in its
MANIFEST.json) carry the join and hole sets; .hgt tiles are built here in
memory, because a real one is 2.9 MB or more.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import math
import random
import subprocess
import sys
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from pathlib import Path

import numpy as np
import pytest

from groundwater.config import TerrainConfig
from groundwater.geo import geodesic_distance_m
from groundwater.geotiff import GeoTiffError, read_geotiff
from groundwater.mapping.elevation import (
    WindowCentre,
    elevation_label_and_credit,
    hgt_layout,
    load_elevation,
    open_elevation_file,
    plan_window,
    read_elevation,
    read_srtm_hgt,
    read_window,
    row_metric,
    sin_cos_deg,
    wgs84_cell_size,
    window_centre,
)
from groundwater.models import SiteMetadata
from groundwater.text import phrase

DEM = Path(__file__).resolve().parent / "webapp" / "fixtures" / "dem"
SETS = json.loads((DEM / "MANIFEST.json").read_text(encoding="ascii"))["sets"]
ARCSEC = 1 / 3600
COPERNICUS_W012 = "Copernicus_DSM_COG_10_N08_00_W012_00_DEM.tif"
COPERNICUS_W011 = "Copernicus_DSM_COG_10_N08_00_W011_00_DEM.tif"


def _builder():
    """make_dem_fixture.py as a module: it is a script, not a package."""
    if "make_dem_fixture" in sys.modules:
        return sys.modules["make_dem_fixture"]
    spec = importlib.util.spec_from_file_location("make_dem_fixture", DEM.parent / "make_dem_fixture.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # a dataclass looks its module up while the class is made
    spec.loader.exec_module(module)
    return module


MAKE = _builder()


def _made(rows, georef, kind="f32", **options) -> bytes:
    """A one-image GeoTIFF from the fixture builder."""
    return MAKE.single("made.tif", "", rows, kind, georef, **options).data


def _files(sources: dict[str, bytes]):
    """Each (name, bytes) opened as an elevation file, and its read_at."""
    readers = {name: (lambda offset, length, data=data: data[offset:offset + length])
               for name, data in sources.items()}
    return ([open_elevation_file(name, len(data), readers[name]) for name, data in sources.items()],
            readers)


def _fixtures(*names: str, rename: dict | None = None) -> dict[str, bytes]:
    rename = rename or {}
    return {rename.get(name, name): (DEM / name).read_bytes() for name in names}


def _read(sources: dict[str, bytes], lon: float, lat: float, radius_km: float, margin_km: float = 0.0,
          cfg: TerrainConfig | None = None, declared=("detect", ""), stride: int = 1):
    """The window around (lon, lat), as if it were a GPS fix."""
    files, readers = _files(sources)
    plan = plan_window(files, WindowCentre(lon, lat, "the test point", True), radius_km, cfg,
                       stride=stride, margin_km=margin_km, declared=declared)
    return read_window(plan, readers, cfg)


def _refused(call, *args, **kwargs) -> GeoTiffError:
    with pytest.raises(GeoTiffError) as refused:
        call(*args, **kwargs)
    assert str(refused.value) == phrase(refused.value.ident, **refused.value.values)
    return refused.value


def _hgt(z_north_first: np.ndarray) -> bytes:
    """An .hgt tile's bytes: big-endian int16, northern row first."""
    return np.asarray(z_north_first, dtype=">i2").tobytes()


def _hgt_heights(side: int, lon0: int, lat0: int, sea=None) -> np.ndarray:
    """Heights north row first, from integer arithmetic on the cells'
    position in the world, so neighbouring tiles agree where they overlap."""
    step = side - 1
    gj = (90 - lat0 - 1) * step + np.arange(side)[:, None]
    gi = (lon0 + 180) * step + np.arange(side)[None, :]
    z = (17 * gi + 29 * gj) % 400 + 10
    if sea is not None:
        z = np.where(sea(gi, gj), 0, z)
    return z


def _centre(read) -> tuple[int, int]:
    return read.grid.z.shape[0] // 2, read.grid.z.shape[1] // 2


# ---------------------------------------------------------------------------
# Joins
# ---------------------------------------------------------------------------

def test_two_abutting_copernicus_tiles_join_without_a_seam():
    """The two GLO-30 clips either side of 11 W read as one grid: every
    column once, on one step, each cell the file's own height. A join that
    repeated or dropped the boundary column would draw a ridge or a step
    along the meridian."""
    assert SETS["copernicus_pair"]["files"] == [COPERNICUS_W012, COPERNICUS_W011]
    sources = _fixtures(COPERNICUS_W012, COPERNICUS_W011)
    read = _read(sources, -11.0, 9.0 - 20 * ARCSEC, 0.5)
    west, east = read_geotiff(DEM / COPERNICUS_W012), read_geotiff(DEM / COPERNICUS_W011)
    joined = np.hstack([west.z, east.z])
    x = np.concatenate([west.x, east.x])
    assert np.all(np.diff(x) > 0) and np.allclose(np.diff(x), ARCSEC, rtol=0, atol=1e-12)
    i = int(np.argmin(np.abs(x - read.grid.lons[0])))
    j = int(np.argmin(np.abs(west.y - read.grid.lats[0])))
    rows, cols = read.grid.z.shape
    assert np.array_equal(read.grid.z, joined[j:j + rows, i:i + cols])
    assert np.allclose(read.grid.lons, x[i:i + cols], rtol=0, atol=1e-12)
    assert (read.voids, read.uncovered, read.implausible, read.coverage) == (0, 0, 0, 1.0)
    grid = read.grid
    assert grid.source_id == "copernicus_glo30" and grid.sea_clean
    assert grid.source == phrase("terrain.label_copernicus", n=2, tiles="N08 W012 and N08 W011")
    assert grid.credit == phrase("terrain.credit_copernicus_modified")
    assert read.notice == phrase("terrain.copernicus_liability")
    assert grid.files == (COPERNICUS_W012, COPERNICUS_W011)


def test_tiles_that_share_an_edge_row_keep_one_copy_when_they_agree():
    """Tiles that repeat their shared row, as .hgt tiles and some clips do,
    give that row once, holding the heights both files give it; a row read
    twice would draw a terrace one cell wide along the join."""
    sources = _fixtures(*SETS["overlap_agree"]["files"])
    shared = 8.75 - 19 * ARCSEC
    read = _read(sources, -12.5 + 12 * ARCSEC, shared, 0.45)
    lats = read.grid.lats
    assert np.all(np.diff(lats) > 0), "a row repeated"
    north = read_geotiff(DEM / "overlap_north.tif")
    south = read_geotiff(DEM / "overlap_south_agrees.tif")
    r = int(np.argmin(np.abs(lats - shared)))
    c = int(np.argmin(np.abs(read.grid.lons - north.x[0])))
    rows = read.grid.z.shape[0]
    assert np.array_equal(read.grid.z[r, c:c + 24], north.z[0])
    assert np.array_equal(read.grid.z[r, c:c + 24], south.z[-1])
    # south.z and north.z run from the south too: the rows either side of the
    # shared one are the next ones of each file, none skipped or repeated
    assert np.array_equal(read.grid.z[:r, c:c + 24], south.z[18 - r:18])
    assert np.array_equal(read.grid.z[r + 1:, c:c + 24], north.z[1:rows - r])


def test_tiles_that_disagree_where_they_overlap_are_refused():
    """Overlapping tiles of one release agree to the bit; three cells that
    differ, by up to 1.2 m, mean mixed releases, and the join is refused
    with the count and the largest difference rather than drawn with
    whichever file happened to come first."""
    sources = _fixtures(*SETS["overlap_disagree"]["files"])
    refusal = _refused(_read, sources, -12.5 + 12 * ARCSEC, 8.75 - 19 * ARCSEC, 0.45)
    assert refusal.ident == "terrain.join_disagree"
    assert refusal.values["a"] == "overlap_north.tif" and refusal.values["b"] == "overlap_south_disagrees.tif"
    assert refusal.values["n"] == 3 and round(refusal.values["m"], 2) == 1.2
    assert "at 3 shared cells, by up to 1.20 m" in str(refusal)


def test_an_undeclared_fill_value_at_a_shared_edge_yields_to_the_other_tiles_height():
    """A -32767 that Copernicus writes without declaring it is not a height
    to compare: the shared row takes the other file's heights, and the
    join stands, because each block's samples are judged before they meet."""
    sources = _fixtures(*SETS["overlap_fill_edge"]["files"])
    shared = 8.75 - 19 * ARCSEC
    read = _read(sources, -12.5 + 12 * ARCSEC, shared, 0.45)
    north = read_geotiff(DEM / "overlap_north.tif")
    r = int(np.argmin(np.abs(read.grid.lats - shared)))
    c = int(np.argmin(np.abs(read.grid.lons - north.x[0])))
    assert np.array_equal(read.grid.z[r, c:c + 24], north.z[0])
    assert read.implausible == 0, "the fill row is covered by the northern file's heights"


def test_files_offset_by_part_of_a_cell_are_refused_rather_than_resampled():
    """Half a cell out of step, or on a different cell size, the files are
    refused: joining them would need resampling, which moves every height."""
    refusal = _refused(_read, _fixtures(*SETS["phase"]["files"]), -12.495, 8.745, 0.2)
    assert refusal.ident == "terrain.join_phase"
    assert (refusal.values["a"], refusal.values["b"]) == ("overlap_north.tif", "phase_half_cell.tif")
    refusal = _refused(_read, _fixtures(*SETS["spacing"]["files"]), -12.495, 8.745, 0.2)
    assert refusal.ident == "terrain.join_spacing"


def test_tiles_from_different_products_are_not_joined():
    """A GLO-30 tile beside an SRTM one is refused: the two describe
    different surfaces on different height datums, and a seam between them
    would be read as a scarp."""
    entry = SETS["products"]
    refusal = _refused(_read, _fixtures(*entry["files"], rename=entry["rename"]), -11.0, 8.995, 0.3)
    assert refusal.ident == "terrain.join_products"
    assert refusal.values == {"a": COPERNICUS_W012, "pa": "Copernicus GLO-30", "b": "n08_w011_1arc_v3.tif",
                              "pb": "SRTM"}


def test_the_reference_file_is_chosen_in_utf16_code_unit_order():
    """Between files at the same corner, the first in plan order is the
    name first in UTF-16 code units, as the browser compares strings: a
    supplementary-plane character before one from U+E000 to U+FFFF, which
    code-point order puts the other way round. The first file's height is
    the one kept, and the one named first when files disagree."""
    rows = MAKE.metres(MAKE.patch(8, 6, 7))
    other = [row[:] for row in rows]
    other[2][3] += 1.0
    georef = MAKE.Georef(-11.5, 8.5, ARCSEC, ARCSEC, raster=2)
    emoji, fullwidth = "tile_\U0001F600.tif", "tile_Ａ.tif"
    assert fullwidth < emoji, "code points put the full-width letter first"
    sources = {fullwidth: _made(rows, georef), emoji: _made(other, georef)}
    files, _ = _files(sources)
    plan = plan_window(files, WindowCentre(-11.5 + 3 * ARCSEC, 8.5 - 2 * ARCSEC, "here", True), 0.06,
                       margin_km=0.0)
    assert [f.name for f in plan.files] == [emoji, fullwidth]
    refusal = _refused(_read, sources, -11.5 + 3 * ARCSEC, 8.5 - 2 * ARCSEC, 0.06)
    assert (refusal.values["a"], refusal.values["b"], refusal.values["n"]) == (emoji, fullwidth, 1)


# ---------------------------------------------------------------------------
# What is accepted
# ---------------------------------------------------------------------------

def test_a_projected_model_is_read_raw_but_refused_as_an_elevation_model_with_its_crs_named():
    """A UTM copy has already been resampled from the tile as published, so
    the elevation layer refuses it, naming the CRS so the operator can tell
    which copy was sent; the raw reader still reads it cell for cell."""
    def crs_refusal(name: str, data: bytes) -> GeoTiffError:
        return _refused(open_elevation_file, name, len(data), lambda offset, length: data[offset:offset + length])

    utm = (DEM / "utm_strip.tif").read_bytes()
    assert read_geotiff(utm).z.shape == (9, 12)
    refusal = crs_refusal("utm_strip.tif", utm)
    assert refusal.ident == "terrain.projected"
    assert refusal.values["crs"] == "WGS 84 / UTM zone 29N (EPSG 32629)"
    assert "is in WGS 84 / UTM zone 29N (EPSG 32629). The toolkit reads" in str(refusal)
    rows = MAKE.metres(MAKE.patch(6, 5, 3))
    sierra_leone = _made(rows, MAKE.Georef(200000.0, 900000.0, 30.0, 30.0, raster=1, model=1, epsg=2161))
    assert crs_refusal("sl.tif", sierra_leone).values["crs"] == "Sierra Leone 1968 / UTM zone 28N (EPSG 2161)"
    assert crs_refusal("pm.tif", (DEM / "refuse_epsg_3857.tif").read_bytes()).values["crs"] == "EPSG 3857"
    assert crs_refusal("none.tif", (DEM / "refuse_no_crs.tif").read_bytes()).ident == "terrain.no_crs"
    nad83 = _made(rows, MAKE.Georef(-11.5, 8.5, ARCSEC, ARCSEC, raster=2, epsg=4269))
    refusal = crs_refusal("nad83.tif", nad83)
    assert (refusal.ident, refusal.values["crs"]) == ("terrain.not_wgs84", "EPSG 4269")
    with pytest.raises(GeoTiffError, match="UTM zone 29N"):
        load_elevation(DEM / "utm_strip.tif")


def test_a_grid_reaching_a_pole_is_refused():
    """Within a degree of a pole a cell has almost no width east to west,
    and at the pole none, which the window arithmetic divides by."""
    data = (DEM / "refuse_polar.tif").read_bytes()
    assert _refused(open_elevation_file, "refuse_polar.tif", len(data),
                    lambda offset, length: data[offset:offset + length]).ident == "terrain.polar"
    rows = MAKE.metres(MAKE.patch(6, 5, 4))
    inside = _made(rows, MAKE.Georef(20.0, 88.99, 0.01, 0.01, raster=2))
    files, _ = _files({"inside.tif": inside})
    assert files[0].layout.y0 == 88.99
    touching = _made(rows, MAKE.Georef(20.0, 89.0, 0.01, 0.01, raster=2))
    assert _refused(_files, {"touching.tif": touching}).ident == "terrain.polar"
    south = _made(rows, MAKE.Georef(20.0, -88.97, 0.01, 0.01, raster=2))  # its last row at 89.01 S
    assert _refused(_files, {"south.tif": south}).ident == "terrain.polar"


# ---------------------------------------------------------------------------
# Source and credit
# ---------------------------------------------------------------------------

def test_a_copernicus_tile_is_credited_only_when_its_name_and_georeferencing_agree():
    """A file named as Copernicus names N08 W012 but placed in another
    square is a file of unstated source, and is said to be one; a GLO-90
    name is not taken for GLO-30, whose licence it does not share."""
    data = (DEM / COPERNICUS_W012).read_bytes()
    files, _ = _files({COPERNICUS_W012: data})
    assert (files[0].source_id, files[0].notes) == ("copernicus_glo30", ())
    lowered = COPERNICUS_W012.lower()
    files, _ = _files({lowered: data})
    assert files[0].source_id == "copernicus_glo30", "names are matched in either case"
    elsewhere = "Copernicus_DSM_COG_10_N07_00_W012_00_DEM.tif"
    read = _read({elsewhere: data}, -11.005, 8.995, 0.2)
    assert read.grid.source_id == "unidentified" and read.grid.credit == "" and read.notice is None
    assert read.prompts == (phrase("terrain.name_mismatch", file=elsewhere),)
    assert read.grid.source == phrase("terrain.label_unidentified", files=elsewhere)
    assert read.figure_credit.startswith(f"Elevation: {read.grid.source}. Cells about 31 by 31 m")
    glo90 = "Copernicus_DSM_COG_30_N08_00_W012_00_DEM.tif"
    files, _ = _files({glo90: data})
    assert (files[0].source_id, files[0].notes) == ("unidentified", ())


def test_a_renamed_tile_is_credited_as_source_not_stated():
    """The same bytes under names Copernicus does not use are not credited
    to Copernicus: nothing in a tile identifies it, and a credit the toolkit
    cannot stand behind is worse than none."""
    sources = _fixtures(*SETS["renamed"]["files"])
    read = _read(sources, -11.0, 8.995, 0.3)
    grid = read.grid
    assert grid.source == phrase("terrain.label_unidentified", files="n08w012.tif and n08w011.tif")
    assert (grid.source_id, grid.credit, grid.sea_clean, read.notice) == ("unidentified", "", False, None)
    assert read.figure_credit == phrase("terrain.figure_credit_bare", label=grid.source, dx=read.plan.dx,
                                        dy=read.plan.dy)
    assert read.surface == phrase("terrain.surface_unknown") and read.notes[-1] == read.surface


def test_an_unnamed_tile_with_the_copernicus_layout_prompts_but_is_not_credited():
    """n08w011.tif is laid out exactly as a GLO-30 tile is, so the operator
    is asked to say whether it is one; it is still not credited. n08w012.tif
    holds the same kind of data but does not start on a whole degree, so it
    does not fit the fingerprint and prompts nothing."""
    read = _read(_fixtures("n08w011.tif"), -10.995, 8.995, 0.2)
    assert read.prompts == (phrase("terrain.looks_copernicus", file="n08w011.tif"),)
    assert read.grid.credit == "" and read.grid.source_id == "unidentified" and read.notice is None
    files, _ = _files(_fixtures("n08w012.tif"))
    assert files[0].notes == ()


def test_a_set_holding_one_copernicus_tile_carries_its_notices():
    """One recognised GLO-30 tile beside a file of unstated source: the
    Copernicus credit and liability sentence go with the set, because the
    licence asks for them on anything made from its data."""
    read = _read(_fixtures(COPERNICUS_W012, "n08w011.tif"), -11.0, 8.995, 0.3)
    assert read.grid.source == phrase("terrain.label_mixed", n=1, tiles="N08 W012", files="n08w011.tif")
    assert read.grid.credit == phrase("terrain.credit_copernicus_modified")
    assert read.notice == phrase("terrain.copernicus_liability")
    assert not read.grid.sea_clean, "a file of unstated source may hold a 0 m fill rather than sea"
    assert read.figure_credit == phrase("terrain.figure_credit", label=read.grid.source, credit=read.grid.credit,
                                        dx=read.plan.dx, dy=read.plan.dy)


def test_an_undeclared_hgt_is_credited_as_source_not_stated():
    """An .hgt tile is SRTM's format, which NASA SRTM, NASADEM and
    void-filled compilations all use, so it is labelled as SRTM-format of
    unstated source, with no product credit; it is still a product that
    writes the sea as 0 m."""
    data = _hgt(_hgt_heights(1201, -13, 8))
    read = _read({"N08W013.hgt": data}, -12.5, 8.5, 0.5)
    grid = read.grid
    assert grid.source == phrase("terrain.label_hgt", n=1, files="N08W013.hgt")
    assert (grid.source_id, grid.credit, grid.sea_clean, read.notice) == ("hgt", "", True, None)
    assert read.surface == phrase("terrain.surface_srtm")


def test_the_operators_declaration_wins_over_detection():
    """What the operator says the files are is what the figures credit,
    whatever the names say; a blank "another source" is no declaration."""
    renamed = _fixtures(*SETS["renamed"]["files"])
    read = _read(renamed, -11.0, 8.995, 0.3, declared=("copernicus_glo30", ""))
    assert read.grid.source == phrase("terrain.label_declared", declared="Copernicus GLO-30",
                                      files="n08w012.tif and n08w011.tif")
    assert read.grid.credit == phrase("terrain.credit_copernicus_modified")
    assert read.notice == phrase("terrain.copernicus_liability") and read.grid.sea_clean
    assert read.prompts == (), "the prompt to declare the source is answered"
    entry = SETS["products"]
    joined = _read(_fixtures(*entry["files"], rename=entry["rename"]), -11.0, 8.995, 0.3,
                   declared=("copernicus_glo30", ""))
    assert joined.grid.source_id == "copernicus_glo30"
    pair = _fixtures(COPERNICUS_W012, COPERNICUS_W011)
    read = _read(pair, -11.0, 8.995, 0.3, declared=("other", "  a drone survey  "))
    assert read.grid.source == phrase("terrain.label_declared", declared="a drone survey",
                                      files=f"{COPERNICUS_W012} and {COPERNICUS_W011}")
    assert (read.grid.credit, read.notice, read.grid.sea_clean) == ("", None, False)
    assert read.surface == phrase("terrain.surface_unknown")
    srtm = _read(pair, -11.0, 8.995, 0.3, declared=("srtm", ""))
    assert srtm.grid.credit == phrase("terrain.credit_srtm") and srtm.notice is None
    blank = _read(pair, -11.0, 8.995, 0.3, declared=("other", " "))
    assert blank.grid.source_id == "copernicus_glo30"
    files, _ = _files(pair)
    assert elevation_label_and_credit(files)[0] == blank.grid.source


def test_a_fabdem_name_carries_the_non_commercial_and_copernicus_warning():
    """A FABDEM tile is licensed for non-commercial use only and made from
    Copernicus data: the operator is told both, and the toolkit credits
    neither, because it cannot tell which licence applies."""
    name = "N08W011_FABDEM_V1-2.tif"
    read = _read({name: (DEM / "n08w011.tif").read_bytes()}, -10.995, 8.995, 0.2)
    assert read.prompts == (phrase("terrain.fabdem_licence", file=name),)
    assert read.grid.source_id == "unidentified" and read.grid.credit == ""
    declared = _read({name: (DEM / "n08w011.tif").read_bytes()}, -10.995, 8.995, 0.2,
                     declared=("copernicus_glo30", ""))
    assert declared.prompts == read.prompts, "a declaration does not answer the licence"


# ---------------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------------

def _model_around(lon: float, lat: float, step: float = 1 / 120, side: int = 61) -> bytes:
    """A small grid centred near (lon, lat), on a lattice of ``step`` degrees."""
    x0 = math.floor(lon / step) * step - (side // 2) * step
    y0 = math.floor(lat / step) * step + (side // 2) * step
    return _made(MAKE.metres(MAKE.patch(side, side, 5)), MAKE.Georef(x0, y0, step, step, raster=2))


def test_the_window_is_centred_on_the_chiefdom_when_there_is_no_gps_fix():
    """With no fix the window is centred on the chiefdom, as every other
    local map is, and the read report says so; with no location at all,
    on the middle of the files."""
    from groundwater.mapping.regional import area_window

    site = SiteMetadata(chiefdom="Koya", district="Port Loko")
    area = area_window(site)
    assert area is not None and not area.exact
    data = _model_around(area.lon, area.lat)
    read = read_elevation([("koya.tif", data)], site=site, radius_km=2.0, margin_km=0.0)
    assert read.centre.label == area.label and not read.centre.exact
    note = phrase("terrain.centre_area", label=area.label)
    assert read.centre.note == note and note in read.notes
    r, c = _centre(read)
    assert abs(read.grid.lons[c] - area.lon) <= 0.5 / 120 and abs(read.grid.lats[r] - area.lat) <= 0.5 / 120
    assert f"around {area.label}, 2 km each way" in read.notes[0]
    files, _ = _files({"koya.tif": data})
    centre = window_centre(None, files)
    assert centre.note == phrase("terrain.centre_no_site") and not centre.exact
    layout = files[0].layout
    assert centre.lon == (layout.x0 + (layout.x0 + 60 * layout.sx)) / 2.0
    assert centre.label == f"{abs(centre.lat):.5f} N, {abs(centre.lon):.5f} W"


def test_the_window_is_read_with_its_margin_and_the_shown_square_inside_it():
    """The analysis reads the margin beyond the square shown on every side,
    and the square shown sits in the middle of what was read, at least the
    radius from the centre each way; with no margin the two are the same."""
    sources = _fixtures(COPERNICUS_W012, COPERNICUS_W011)
    radius, margin = 0.3, 0.2
    read = _read(sources, -11.0, 8.995, radius, margin)
    plan = read.plan
    dx, dy = wgs84_cell_size(plan.lats[plan.hy], ARCSEC, ARCSEC)
    assert (plan.hx, plan.hy) == (math.ceil(500 / dx), math.ceil(500 / dy))
    assert (plan.hxs, plan.hys) == (math.ceil(300 / dx), math.ceil(300 / dy))
    r0, r1, c0, c1 = read.shown
    rows, cols = read.grid.z.shape
    assert (rows, cols) == (2 * plan.hy + 1, 2 * plan.hx + 1) and read.cells == rows * cols
    assert (r0 + r1 - 1, c0 + c1 - 1) == (rows - 1, cols - 1), "the square shown is centred"
    assert (c1 - 1 - plan.hx) * dx >= radius * 1000 and (r1 - 1 - plan.hy) * dy >= radius * 1000
    assert plan.hx * dx >= (radius + margin) * 1000
    assert phrase("terrain.read_margin", margin=margin) in read.notes
    flat = _read(sources, -11.0, 8.995, radius, 0.0)
    assert flat.shown == (0, flat.grid.z.shape[0], 0, flat.grid.z.shape[1])
    assert not any("beyond the square shown" in note for note in flat.notes)
    assert np.array_equal(read.grid.z[r0:r1, c0:c1], flat.grid.z)


def test_the_read_says_how_much_of_the_window_the_files_cover():
    """A window that runs off the files reads as a gap there, counted and
    said, rather than being cut down to the files without a word."""
    read = _read(_fixtures("n08w011.tif"), -11.0, 9.0, 0.3)
    rows, cols = read.grid.z.shape
    assert (rows, cols) == (21, 21)
    assert read.uncovered == 21 * 21 - 11 * 11 and read.coverage == 121 / 441
    assert int(np.isnan(read.grid.z).sum()) == read.uncovered
    assert phrase("terrain.read_uncovered", pct=100 * 320 / 441) in read.notes
    assert "73% of the window read lies outside the files supplied" in read.notes[1]


def _holes(set_name: str, lon=-12.0, lat=8.0, radius=30.0, declared=None):
    entry = SETS[set_name]
    return _read(_fixtures(*entry["files"]), lon, lat, radius,
                 declared=declared or (entry.get("declare", "detect"), ""))


def test_a_missing_tile_whose_full_edges_are_sea_is_taken_as_sea_with_no_height():
    """N07 W013 is missing from a Copernicus set whose tiles beside it are
    sea all along their shared edges: it is open sea, which Copernicus
    publishes no tiles for. It has no height, and its edge blocks are read
    even where they lie outside the window."""
    read = _holes("holes_sea")
    plan = read.plan
    assert plan.tile == 40 and plan.missing == ((0, 1),)
    assert sorted((plan.files[e.file].name, e.row, e.column) for e in plan.edges) == [
        ("holes_sea_N07W012.tif", None, 0), ("holes_sea_N08W013.tif", 39, None)]
    assert any(block.edges and not block.window for block in plan.blocks), "an edge block outside the window"
    lons, lats = read.grid.lons, read.grid.lats
    tile = (lons < -12.0 - 1e-9)[None, :] & (lats < 8.0 + 1e-9)[:, None]
    assert np.array_equal(read.assumed_sea, tile)
    assert np.isnan(read.grid.z[tile]).all() and not np.isnan(read.grid.z[~tile]).any()
    assert (read.assumed, read.uncovered) == (int(tile.sum()), 0)
    assert read.coverage == (read.cells - read.assumed) / read.cells
    sentence = phrase("terrain.read_assumed_sea", pct=100 * read.assumed / read.cells, n=1, tiles="N07 W013",
                      level=0.0, product="Copernicus GLO-30")
    assert sentence in read.notes


def test_a_missing_tile_beside_land_stays_a_void():
    """Where the tiles beside the missing one hold land along their edges,
    the missing tile is a gap: a land tile the operator forgot."""
    read = _holes("holes_land")
    assert read.plan.missing == ((0, 1),)
    assert read.assumed == 0 and not read.assumed_sea.any()
    assert read.uncovered == 11 * 12
    assert phrase("terrain.read_uncovered", pct=100 * read.uncovered / read.cells) in read.notes


def test_a_missing_tile_whose_full_edge_holds_land_stays_a_void_even_where_the_window_sees_only_sea():
    """N08 W013's last row is sea where the window meets it but land west of
    12.5 W, so N07 W013 may hold land: the test is the full edge, not the
    part the window happens to see."""
    read = _holes("holes_edge", radius=15.0)
    lats, lons = read.grid.lats, read.grid.lons
    row = int(np.argmin(np.abs(lats - (8.0 + 1 / 40))))
    seen = read.grid.z[row, lons < -12.0 - 1e-9]
    assert seen.size and (seen <= 0.0).all(), "the window sees only sea on the shared edge"
    assert read.assumed == 0 and read.uncovered > 0


def test_an_undeclared_fill_value_beside_a_hole_keeps_the_hole_a_void():
    """N08 W013 ends in two columns of -3.4e38 beside the missing N08 W012.
    Judged before anything uses them, they are implausible, so the edge
    holds no height at all and the missing tile is a gap, not sea."""
    read = _holes("hole_fill_margin", lon=-12.02, lat=8.5, radius=8.0)
    assert read.plan.missing == ((1, 0),)
    assert read.assumed == 0 and read.uncovered == 3 * 7
    assert read.implausible == 2 * 7
    assert phrase("terrain.read_implausible", n=14, lo=-1000.0, hi=9000.0) in read.notes


def test_files_of_unstated_source_never_assume_sea():
    """Without a product that publishes no sea tiles, a missing tile is a
    gap whatever its neighbours hold: a GDAL mosaic fills gaps with 0 m."""
    read = _holes("holes_sea", declared=("detect", ""))
    assert read.plan.tile == 0 and read.plan.missing == ()
    assert read.assumed == 0 and read.uncovered == 11 * 12
    mixed = _holes("holes_sea", declared=("other", "a mosaic"))
    assert mixed.assumed == 0


def test_an_hgt_set_takes_a_missing_tile_as_sea_on_its_shared_edges():
    """.hgt tiles repeat their shared rows and columns (1201 samples a side
    for 1200 cells), so the row a missing tile shares with its northern
    neighbour is supplied, and the rest of it is sea when both full edges
    beside it are."""
    # sea south-west of 12 W, 8 N, reaching 30 cells beyond each into the
    # tiles supplied, so their full edges with N07 W013 are sea, and their
    # edges with N08 W012, also missing, are land
    corner_i, corner_j = (180 - 12) * 1200, (90 - 8) * 1200

    def sea(gi, gj):
        return (gi <= corner_i + 30) & (gj >= corner_j - 30)

    sources = {"N08W013.hgt": _hgt(_hgt_heights(1201, -13, 8, sea)),
               "N07W012.hgt": _hgt(_hgt_heights(1201, -12, 7, sea))}
    read = _read(sources, -12.02, 8.02, 5.0, declared=("detect", ""))
    plan = read.plan
    assert plan.tile == 1200 and plan.missing == ((1, 0), (0, 1))
    lats, lons = read.grid.lats, read.grid.lons
    south_west = (lats < 8.0 - 1e-9)[:, None] & (lons < -12.0 - 1e-9)[None, :]
    north_east = (lats > 8.0 + 1e-9)[:, None] & (lons > -12.0 + 1e-9)[None, :]
    assert np.array_equal(read.assumed_sea, south_west), "N07 W013 is sea"
    assert read.uncovered == int(north_east.sum()), "N08 W012 is a gap"
    assert np.isnan(read.grid.z[south_west | north_east]).all()
    assert not np.isnan(read.grid.z[~(south_west | north_east)]).any(), "8 N and 12 W are supplied"
    # one metre of land anywhere on that edge, far outside the window, and
    # the missing tile may hold land too
    north = _hgt_heights(1201, -13, 8, sea)
    north[-1, 10] = 1
    sources["N08W013.hgt"] = _hgt(north)
    read = _read(sources, -12.02, 8.02, 5.0)
    assert read.assumed == 0 and read.uncovered == int((south_west | north_east).sum())


def test_a_window_over_the_cap_is_refused_with_a_radius_that_fits():
    """Over the cap the refusal says which radius fits once the margin is
    added, and that radius does fit: an answer the operator can act on."""
    cfg = dataclasses.replace(TerrainConfig(), max_cells=10_000)
    sources = _fixtures(COPERNICUS_W012, COPERNICUS_W011)
    refusal = _refused(_read, sources, -11.0, 8.995, 1.1, 0.5, cfg)
    assert refusal.ident == "terrain.too_many_cells"
    fit = refusal.values["fit"]
    assert fit == 0.9 and refusal.values["cap"] == 10_000 and refusal.values["margin"] == 0.5
    assert "a radius of 0.9 km fits" in str(refusal) and "than the 10,000 the analysis takes" in str(refusal)
    read = _read(sources, -11.0, 8.995, fit, 0.5, cfg)
    assert read.cells <= 10_000


def test_implausible_and_infinite_heights_become_counted_voids():
    """An infinity or a fill value nobody declared is voided and counted,
    and the read report says how many; a declared no-data value is counted
    as no data. Neither refuses the file over a few cells."""
    read = _read(_fixtures("inf_f32.tif"), -10.6996 + 6 / 1200, 8.9996 - 5 / 1200, 0.6)
    assert (read.implausible, read.voids) == (4, 0)
    assert phrase("terrain.read_implausible", n=4, lo=-1000.0, hi=9000.0) in read.notes
    read = _read(_fixtures("be_lzw_p2_int16.tif"), -11.8 + 9 / 1200, 7.98 - 8 / 1200, 0.9)
    assert (read.voids, read.implausible) == (3, 0)
    assert phrase("terrain.read_voids", n=3) in read.notes
    assert int(np.isnan(read.grid.z).sum()) == read.voids + read.uncovered


def test_an_hgt_window_reads_only_its_rows_and_equals_the_whole_tile_slice(tmp_path):
    """A window of an .hgt reads its own rows and no others, and holds what
    the whole-tile reader gives for those cells, voids included."""
    z = _hgt_heights(1201, -13, 8)
    z[600, 595:600] = -32768
    data = _hgt(z)
    reads: list[tuple[int, int]] = []

    def read_at(offset: int, length: int) -> bytes:
        reads.append((offset, length))
        return data[offset:offset + length]

    found = open_elevation_file("N08W013.hgt", len(data), read_at)
    assert reads == [], "an .hgt needs no bytes to be laid out"
    plan = plan_window([found], WindowCentre(-12.5, 8.5, "here", True), 2.0, margin_km=0.0)
    read = read_window(plan, {"N08W013.hgt": read_at})
    first_row, last_row = plan.cj - plan.hy, plan.cj + plan.hy
    assert all(2 * 1201 * first_row <= offset and offset + length <= 2 * 1201 * (last_row + 1)
               for offset, length in reads)
    assert sum(length for _, length in reads) == 2 * 1201 * plan.height
    path = tmp_path / "N08W013.hgt"
    path.write_bytes(data)
    whole = read_srtm_hgt(path)
    j = 1200 - last_row
    i = plan.ci - plan.hx
    expected = whole.z[j:j + plan.height, i:i + plan.width]
    assert np.array_equal(read.grid.z, expected, equal_nan=True)
    assert read.voids == 5
    assert np.allclose(read.grid.lons, whole.lons[i:i + plan.width], rtol=0, atol=1e-12)
    assert np.allclose(read.grid.lats, whole.lats[j:j + plan.height], rtol=0, atol=1e-12)


def test_an_hgt_pair_across_a_parallel_reads_as_one_grid():
    """Two .hgt tiles either side of 9 N repeat the 9 N row; it is read
    once, from the northern tile, which comes first in plan order, and the
    rows either side are each tile's own."""
    north = _hgt_heights(1201, -13, 9)
    south = _hgt_heights(1201, -13, 8)
    assert np.array_equal(north[-1], south[0]), "the tiles agree on their shared row"
    read = _read({"N09W013.hgt": _hgt(north), "N08W013.hgt": _hgt(south)}, -12.5, 9.0, 0.2)
    assert [f.name for f in read.plan.files] == ["N09W013.hgt", "N08W013.hgt"]
    assert np.all(np.diff(read.grid.lats) > 0) and read.uncovered == 0
    r, c = _centre(read)
    assert read.grid.z[r, c] == north[-1, 600]
    assert read.grid.z[r + 1, c] == north[-2, 600] and read.grid.z[r - 1, c] == south[1, 600]


def test_a_set_is_refused_for_a_repeated_name_mixed_kinds_or_a_window_it_cannot_hold():
    """The plan's refusals, each with its own sentence: one file given
    twice, GeoTIFF beside .hgt, a centre off the files, a window too small
    to analyse, and a window with no height in it. Without them the operator
    would get an empty map, or one of a place they did not ask for."""
    tif = (DEM / "n08w011.tif").read_bytes()
    files, _ = _files({"a.tif": tif})
    twice = [files[0], files[0]]
    centre = WindowCentre(-10.995, 8.995, "here", True)
    assert _refused(plan_window, twice, centre, 0.3, margin_km=0.0).ident == "terrain.duplicate_name"
    hgt, _ = _files({"N08W011.hgt": _hgt(_hgt_heights(1201, -11, 8))})
    refusal = _refused(plan_window, [files[0], hgt[0]], centre, 0.3, margin_km=0.0)
    assert refusal.ident == "terrain.mixed_formats"
    refusal = _refused(plan_window, files, WindowCentre(-10.0, 8.0, "Bo", True), 0.3, margin_km=0.0)
    assert refusal.ident == "terrain.site_outside" and refusal.values["where"] == "Bo"
    assert refusal.values["extent"] == "8.989-9.000 N, 10.989-11.000 W"
    refusal = _refused(plan_window, files, centre, 0.0, margin_km=0.0)
    assert (refusal.ident, refusal.values["w"], refusal.values["h"]) == ("terrain.too_small", 1, 1)
    void = _made([[-32767.0] * 6] * 5, MAKE.Georef(-11.5, 8.5, ARCSEC, ARCSEC, raster=2))
    refusal = _refused(_read, {"void.tif": void}, -11.5 + 2 * ARCSEC, 8.5 - 2 * ARCSEC, 0.05)
    assert refusal.ident == "terrain.no_elevations" and refusal.values["where"] == "the test point"


def test_an_hgt_tile_is_placed_by_its_name_and_sized_by_its_length():
    """An .hgt has no header: its corner is its name and its resolution its
    length, and a name or a length that does not say is refused in the
    sentences the whole-tile reader has always used."""
    layout = hgt_layout("s05e012.hgt", 2 * 3601 * 3601)
    assert (layout.x0, layout.y0, layout.width, layout.rows_per_strip) == (12.0, -4.0, 3601, 1)
    assert layout.sx == 1.0 / 3600 and layout.nodata == -32768 and layout.byte_order == ">"
    assert layout.offsets[2] == 4 * 3601 and layout.byte_counts[2] == 2 * 3601
    refusal = _refused(hgt_layout, "tile.hgt", 2 * 1201 * 1201)
    assert refusal.ident == "terrain.hgt_name" and "does not name its corner" in str(refusal)
    refusal = _refused(hgt_layout, "N08W013.hgt", 2 * 1000 * 1000 + 1)
    assert refusal.values["n"] == 1000 * 1000 and "1000000 samples" in str(refusal)


def test_a_strided_window_reads_every_nth_cell_of_the_full_window():
    """The Python app's wide topographic map reads every stride-th cell,
    with no averaging: the same heights as the full window at those cells.
    A stride of 0 chooses the least that fits under the cap."""
    data = _hgt(_hgt_heights(1201, -13, 8))
    full = _read({"N08W013.hgt": data}, -12.5, 8.5, 3.0)
    strided = _read({"N08W013.hgt": data}, -12.5, 8.5, 3.0, stride=3)
    assert full.grid.z.shape == (67, 67) and strided.grid.z.shape == (23, 23)
    assert np.array_equal(strided.grid.z, full.grid.z[::3, ::3])
    assert strided.grid.lons.tolist() == full.grid.lons[::3].tolist()
    assert strided.grid.lats.tolist() == full.grid.lats[::3].tolist()
    assert len(strided.plan.blocks) == 23, "only the rows read are decoded"
    cfg = dataclasses.replace(TerrainConfig(), max_cells=500)
    auto = _read({"N08W013.hgt": data}, -12.5, 8.5, 3.0, cfg=cfg, stride=0)
    assert auto.cells <= 500 and auto.plan.stride > 1


# ---------------------------------------------------------------------------
# Axes and metres
# ---------------------------------------------------------------------------

def test_the_axes_are_computed_as_origin_plus_index_times_step():
    """Each centre is the origin plus its index times the step, one product
    and one sum, as the browser computes it; arange and linspace round
    differently and would put the two engines a bit apart."""
    read = _read(_fixtures(COPERNICUS_W012, COPERNICUS_W011), -11.0, 8.995, 0.4, 0.1)
    plan = read.plan
    lons = [plan.x0 + (plan.ci - plan.hx + k) * plan.sx for k in range(plan.width)]
    lats = [plan.y0 - (plan.cj + plan.hy - r) * plan.sy for r in range(plan.height)]
    assert read.grid.lons.tolist() == lons and read.grid.lats.tolist() == lats


def _reference_sin_cos(d: float) -> tuple[float, float]:
    """sin and cos of d degrees to 60 digits, then rounded to a double."""
    pi = Decimal("3.14159265358979323846264338327950288419716939937510582097494459230781640628620899")
    with localcontext() as ctx:
        ctx.prec = 60
        x = Decimal(d) * pi / 180
        k = int((x / (pi / 2)).to_integral_value(rounding=ROUND_HALF_EVEN))
        r = x - k * (pi / 2)
        r2 = r * r
        s = term = r
        n = 1
        while abs(term) > Decimal("1e-55"):
            term = -term * r2 / ((2 * n) * (2 * n + 1))
            s += term
            n += 1
        c = term = Decimal(1)
        n = 1
        while abs(term) > Decimal("1e-55"):
            term = -term * r2 / ((2 * n - 1) * (2 * n))
            c += term
            n += 1
        return [(float(s), float(c)), (float(c), float(-s)), (float(-s), float(-c)), (float(-c), float(s))][k % 4]


def test_degree_sine_and_cosine_are_within_two_ulps_and_exact_at_right_angles():
    """The polynomial sine and cosine every cell size comes from are within
    two units in the last place of the true values, and exactly 0 or 1 at
    right angles, where libm's sin(radians(180)) is not; the browser's
    copy must give the same bits, which libm on two engines does not."""
    rng = random.Random(41)
    inputs = [k * 0.25 for k in range(-2880, 2881)]
    inputs += [8 + rng.random() * 4 for _ in range(1000)] + [rng.uniform(-720, 720) for _ in range(1000)]
    inputs += [1e-7, -1e-7, 5e-324, 89.99999, 90.00001, -0.0]
    for d in inputs:
        got = sin_cos_deg(d)
        if d % 90 == 0:
            quarter = round(d / 90) % 4
            assert got == ((0.0, 1.0), (1.0, 0.0), (0.0, -1.0), (-1.0, 0.0))[quarter], d
            continue
        for value, want in zip(got, _reference_sin_cos(d), strict=True):
            assert abs(value - want) <= 2 * math.ulp(want), (d, value, want)
    assert math.sin(math.radians(180)) != 0.0
    assert all(math.isnan(v) for v in sin_cos_deg(float("inf")))


def test_cell_sizes_follow_the_wgs84_ellipsoid_row_by_row():
    """Each row's cell is as wide and as tall as the ellipsoid says at its
    own latitude, checked against Vincenty's geodesic distance: across one
    tile the width changes by 0.26%, which a single figure for the whole
    window would get wrong at one edge or the other."""
    step = ARCSEC
    for lat in (-30.0, 0.0, 7.0, 8.5, 9.75, 12.0, 60.0):
        dx, dy = wgs84_cell_size(lat, step, step)
        along = geodesic_distance_m(lat, -11.0, lat, -11.0 + step)
        across = geodesic_distance_m(lat - step / 2, -11.0, lat + step / 2, -11.0)
        assert abs(dx - along) <= 1e-7 * along, (lat, dx, along)
        assert abs(dy - across) <= 1e-7 * across, (lat, dy, across)
    dx, dy = wgs84_cell_size(8.5, step, step)
    assert (round(dx, 4), round(dy, 4), math.floor(dx * dy * 100.0 + 0.5)) == (30.5847, 30.7218, 93962)
    lons = -11.5 + np.arange(5) * step
    lats = 8.0 + np.arange(3600) * step
    metric = row_metric(lons, lats)
    assert metric.dx[-1] < metric.dx[0] * (1 - 0.0025)
    for r in (0, 1800, 3599):
        x, y = wgs84_cell_size(float(lats[r]), (lons[-1] - lons[0]) / 4, (lats[-1] - lats[0]) / 3599)
        assert (metric.dx[r], metric.dy[r]) == (x, y)
        assert metric.dg[r] == math.sqrt(x * x + y * y)
        assert metric.au_row[r] == math.floor(x * y * 100.0 + 0.5)


def test_importing_the_elevation_layer_does_not_import_pyplot():
    """Reading a window of an elevation model, with no site to centre it
    on, loads no matplotlib: the terrain analysis and the browser's
    Pyodide build read windows without the plotting stack."""
    code = (
        "import sys\n"
        "from groundwater.mapping.elevation import read_elevation\n"
        f"read = read_elevation([('n08w011.tif', {str(DEM / 'n08w011.tif')!r})], radius_km=0.2, margin_km=0.1)\n"
        "print(read.cells, sorted(m for m in sys.modules if m.split('.')[0] == 'matplotlib'))\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "441 []"

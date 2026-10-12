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
    ElevationFile,
    WindowCentre,
    _percent,
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


def test_a_file_with_a_gdal_mask_is_refused_as_an_elevation_model_but_read_raw():
    """GDAL keeps a mask of invalid cells as a directory after the image, and
    the cells it hides usually hold 0. Read as heights they would be ground
    at sea level, which the sea rule could then take for sea, and nothing in
    the report would say a mask was dropped; so the elevation layer refuses
    the file, asking for a no-data value instead, whether it is opened for a
    window or read whole. The raw layer still reads every sample."""
    for name in ("internal_mask.tif", "gdal_internal_mask_f32.tif"):
        data = (DEM / name).read_bytes()
        assert read_geotiff(data, name).layout.has_mask
        refusal = _refused(_files, {name: data})
        assert (refusal.ident, refusal.values) == ("terrain.internal_mask", {"file": name})
        assert str(refusal) == (f"{name} marks some of its cells as invalid with a GDAL mask, which this "
                                "reader does not apply; save it again with a no-data value instead.")
        assert _refused(load_elevation, DEM / name).ident == "terrain.internal_mask"


def test_masks_gdal_writes_with_its_gtiff_and_cog_drivers_are_refused(tmp_path):
    """The two ways GDAL puts a mask beside an elevation model - the GTiff
    driver with GDAL_TIFF_INTERNAL_MASK, and the COG driver copying a masked
    source, which puts the mask after the image and overviews after both -
    each refused by the elevation layer, so a masked file from either never
    reads its hidden cells as heights."""
    rasterio = pytest.importorskip("rasterio")
    from rasterio.shutil import copy as gdal_copy
    from rasterio.transform import from_origin

    heights = np.full((64, 64), 25.0, dtype="float32")
    heights[:, :20] = 0.0
    valid = np.full((64, 64), 255, dtype="uint8")
    valid[:, :20] = 0
    profile = {"driver": "GTiff", "width": 64, "height": 64, "count": 1, "dtype": "float32",
               "crs": "EPSG:4326", "transform": from_origin(-12.0, 9.0, ARCSEC, ARCSEC), "compress": "deflate"}
    gtiff = tmp_path / "masked.tif"
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True), rasterio.open(gtiff, "w", **profile) as sink:
        sink.write(heights, 1)
        sink.write_mask(valid)
    cog = tmp_path / "masked_cog.tif"
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True), rasterio.open(gtiff) as source:
        assert source.mask_flag_enums[0][0].name == "per_dataset"
        gdal_copy(source, str(cog), driver="COG", BLOCKSIZE="16", OVERVIEWS="AUTO")
    for path in (gtiff, cog):
        data = path.read_bytes()
        assert read_geotiff(data).layout.has_mask, path.name
        assert _refused(_files, {path.name: data}).ident == "terrain.internal_mask", path.name


@pytest.mark.parametrize(("label", "georef"), [
    ("a NaN tiepoint", MAKE.Georef(math.nan, 8.0, ARCSEC, ARCSEC, raster=2, copernicus_keys=True)),
    ("an infinite tiepoint", MAKE.Georef(math.inf, 8.0, ARCSEC, ARCSEC, raster=2, copernicus_keys=True)),
    ("a tiepoint at minus infinity", MAKE.Georef(-math.inf, 8.0, 0.001, 0.001)),
    ("a tiepoint at 1.7e308", MAKE.Georef(1.7e308, 8.0, 0.001, 0.001, raster=1)),
    ("a NaN translation", MAKE.Georef(math.nan, 8.0, ARCSEC, ARCSEC, transform=True)),
    ("a subnormal cell width", MAKE.Georef(-12.0, 8.0, 1e-320, 0.001)),
    ("an infinite cell height", MAKE.Georef(-12.0, 8.0, 0.001, math.inf)),
    ("a cell just under 1e-7 degree", MAKE.Georef(-12.0, 8.0, 0.001, 9.9e-8)),
    ("a cell of two degrees", MAKE.Georef(-12.0, 8.0, 2.0, 0.5)),
    ("longitudes past 540 degrees", MAKE.Georef(535.0, 8.0, 1.0, 0.5)),
    ("a first row north of the pole", MAKE.Georef(-12.0, 90.5, 0.01, 0.01)),
])
def test_damaged_georeferencing_is_refused_as_the_file_is_opened(label, georef):
    """An origin that is not a number or infinite, longitudes beyond any map
    or a cell size no elevation model has (under 1e-7 or over 1 degree)
    comes from a damaged header. Each is refused, with its own sentence, as
    the file is opened, so that none reaches the source recognition or the
    window arithmetic, where Python's integer conversions raised a bare
    ValueError or an OverflowError the apps did not catch, the browser
    carried a NaN on into another refusal, and a cell 1e-156 degree tall
    hung the Python app's stride search. The refusal is a ValueError, as
    the Streamlit page catches."""
    data = _made(MAKE.metres(MAKE.patch(12, 12, 7)), georef)
    refusal = _refused(_files, {"damaged.tif": data})
    assert (refusal.ident, refusal.values) == ("terrain.bad_georeference", {"file": "damaged.tif"}), label
    assert isinstance(refusal, ValueError)
    with pytest.raises(ValueError, match="georeferencing is damaged"):
        read_elevation([("damaged.tif", data)], None, 5.0, stride=0, margin_km=0.0)


def test_a_corrupted_pixel_scale_is_refused_at_once_rather_than_hanging_the_stride_search():
    """One flipped bit in ModelPixelScale made a cell 1.9e-156 degree tall;
    the app's stride search then stepped up a stride at a time for longer
    than the process would live. Refused as the file is opened now, and the
    search itself is a binary one that ends whatever it is given."""
    data = bytearray((DEM / "holes_sea_N07W012.tif").read_bytes())
    data[293] = 0x1F
    refusal = _refused(read_elevation, [("holes_sea_N07W012.tif", bytes(data))], None, 5.0, stride=0,
                       margin_km=0.0)
    assert refusal.ident == "terrain.bad_georeference"
    accepted = _made(MAKE.metres(MAKE.patch(6, 5, 4)), MAKE.Georef(-12.0, 8.0, 1e-7, 1.0))
    assert _files({"edge.tif": accepted})[0][0].layout.sx == 1e-7, "the least cell size is taken"


def test_the_least_stride_is_found_by_a_search_that_ends_on_any_window():
    """_least_stride gives the least stride at which the window fits the cap,
    as stepping up from the estimate did, but in a logarithmic number of
    steps: a window of 10**154 cells a side is answered at once, a window
    already under the cap takes stride 1, and a cap under 9 cells, which no
    window fits, gives the stride at which the window is 3 by 3. Prevents a
    damaged cell size hanging the Python app's topographic map."""
    from groundwater.mapping.elevation import _least_stride

    def fits(hx, hy, stride, cap):
        return (2 * -(-hx // stride) + 1) * (2 * -(-hy // stride) + 1) <= cap

    assert _least_stride(2, 2, 25) == 1 and _least_stride(0, 0, 1) == 1
    huge = _least_stride(2, 10**154, 2_000_000)
    assert fits(2, 10**154, huge, 2_000_000) and not fits(2, 10**154, huge - 1, 2_000_000)
    assert _least_stride(300, 400, 8) == 400
    rng = random.Random(4103)
    for _ in range(2000):
        # the old search: up from the estimate a stride at a time
        hx, hy, cap = rng.randint(0, 5000), rng.randint(0, 5000), rng.randint(9, 3_000_000)
        stride = max(1, math.ceil(math.sqrt((2 * hx + 1) * (2 * hy + 1) / cap)))
        while not fits(hx, hy, stride, cap):
            stride += 1
        assert _least_stride(hx, hy, cap) == stride, (hx, hy, cap)


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
    # the summary counts the square shown, as its radius says, so the margin
    # does not change it
    assert read.notes[0] == flat.notes[0]
    assert read.notes[0].startswith(f"Read 2 files ({COPERNICUS_W012} and {COPERNICUS_W011}): 441 cells about")
    assert read.cells == 1225 and (r1 - r0) * (c1 - c0) == 441


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


def test_the_read_report_names_only_the_files_a_window_reads():
    """A window inside one tile of a pair reads that tile alone, and the
    report says "Read 1 file", naming it, as the grid's files do; the label
    and credit stay the whole set's. A tile whose edge alone is read, to
    decide whether a missing tile is sea, is read, and named. Prevents the
    report claiming files it never opened a block of."""
    sources = _fixtures(COPERNICUS_W012, COPERNICUS_W011)
    files, _ = _files(sources)
    west = files[0].layout if files[0].name == COPERNICUS_W012 else files[1].layout
    inside = _read(sources, west.x0 + 34 * ARCSEC, 8.995, 0.1)
    assert {b.file for b in inside.plan.blocks} == {0} and inside.plan.files[0].name == COPERNICUS_W012
    assert inside.notes[0].startswith(f"Read 1 file ({COPERNICUS_W012}): 81 cells about 31 by 31 m")
    assert inside.grid.files == (COPERNICUS_W012,)
    assert inside.grid.source == phrase("terrain.label_copernicus", n=2, tiles="N08 W012 and N08 W011")
    across = _read(sources, -11.0, 8.995, 0.2)
    assert across.notes[0].startswith(f"Read 2 files ({COPERNICUS_W012} and {COPERNICUS_W011})")
    # a window in N07 W012 reaching west into the missing N07 W013 but not
    # north to 8 N: N08 W013 gives up its last row alone, and N08 W012 nothing
    sea = _holes("holes_sea", lon=-11.99, lat=7.5, radius=5.0)
    assert {sea.plan.files[b.file].name for b in sea.plan.blocks if b.window} == {"holes_sea_N07W012.tif"}
    assert sea.grid.files == ("holes_sea_N08W013.tif", "holes_sea_N07W012.tif") and sea.assumed
    assert sea.notes[0].startswith("Read 2 files (holes_sea_N08W013.tif and holes_sea_N07W012.tif)")


def test_a_gap_or_a_sea_under_half_a_percent_is_said_to_be_under_1_percent_never_0():
    """A gap or an assumed sea is reported only because it is there, so a
    share that would round to 0% is written as less than 1% with its count
    of cells, and one short of the whole never as 100%; every other share is
    a whole percentage rounded half up in integers, so both engines print
    the same figure. Prevents "0% of the window read lies outside the
    files", a sentence that contradicts itself."""
    tile = {"N08W012.hgt": _hgt(_hgt_heights(1201, -12, 8))}
    under = _read(tile, -11.5, 9 - 162 / 1200, 15.0)
    assert (under.uncovered, under.cells) == (329, 107_583)
    assert phrase("terrain.read_uncovered_little", count=329) in under.notes
    assert "Less than 1% of the window read (329 cells) lies outside the files supplied" in under.notes[1]
    assert not any(note.startswith("0%") for note in under.notes)
    over = _read(tile, -11.5, 9 - 161 / 1200, 15.0)
    assert over.uncovered == 658 and phrase("terrain.read_uncovered", pct=1) in over.notes
    # a sea tile the window just reaches at a corner
    corner_i, corner_j = (180 - 12) * 1200, (90 - 8) * 1200

    def sea(gi, gj):
        return (gi <= corner_i + 30) & (gj >= corner_j - 30)

    tiles = {name: _hgt(_hgt_heights(1201, lon0, lat0, sea))
             for name, lon0, lat0 in (("N08W013.hgt", -13, 8), ("N08W012.hgt", -12, 8), ("N07W012.hgt", -12, 7))}
    read = _read(tiles, -12 + 50 / 1200, 8 + 50 / 1200, 5.0)
    assert read.assumed == 25 and 200 * read.assumed < read.cells
    assert phrase("terrain.read_assumed_sea_little", count=25, n=1, tiles="N07 W013", level=0.0,
                  product="SRTM") in read.notes
    for count, cells, pct in ((1, 200, 1), (3, 600, 1), (5, 1000, 1), (995, 1000, 99), (999, 1000, 99),
                              (1000, 1000, 100), (989, 1000, 99), (985, 1000, 99), (984, 1000, 98),
                              (320, 441, 73), (7, 8, 88), (1, 8, 13)):
        assert _percent(count, cells) == pct, (count, cells)


def test_a_missing_tile_is_named_as_sea_only_where_some_window_cell_of_it_is_sea():
    """An .hgt tile's last row and column are the next tiles' first, so a
    window whose edge lies on that shared column meets the tile to the east
    without a cell of it going uncovered. The report names, as taken for
    sea, only the missing tiles that hold a window cell taken as sea.
    Prevents a sentence placing sea east of a line the window never
    crosses."""
    z = _hgt_heights(1201, -12, 8)
    z[-1, :] = 0
    z[:, -1] = 0
    read = _read({"N08W012.hgt": _hgt(z)}, -12 + 1189 / 1200, 9 - 1195 / 1200, 1.0)
    assert read.plan.missing == ((1, 0), (0, 1), (1, 1))
    sea_note = next(note for note in read.notes if "taken as open sea" in note)
    assert sea_note == phrase("terrain.read_assumed_sea", pct=_percent(read.assumed, read.cells), n=1,
                              tiles="N07 W012", level=0.0, product="SRTM")
    assert "N08 W011" not in sea_note


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


def test_every_radius_the_cap_offers_fits_and_a_margin_alone_over_the_cap_offers_none():
    """A sweep over caps, margins, radii, latitudes and the spacings tiles
    come in: whenever too_many_cells offers a radius, a window of that
    radius plans; when the margin alone needs more cells than the cap,
    margin_too_many_cells says so and offers no radius, rather than the
    "a radius of 0 km fits" that the plan then refused again. Prevents the
    refusal giving advice that does not work."""
    rng = random.Random(4104)
    offered = margins = 0
    for _ in range(400):
        step = rng.choice([ARCSEC, 1 / 1200, 1 / 40, 0.01])
        lat = rng.uniform(-60.0, 60.0)
        layout = dataclasses.replace(hgt_layout("N00E000.hgt", 2 * 1201 * 1201), x0=0.0, y0=lat, sx=step,
                                     sy=step, width=100_000, height=100_000, tiled=True, block_width=1024,
                                     block_height=1024, rows_per_strip=None, offsets=[0] * 98 * 98,
                                     byte_counts=[0] * 98 * 98)
        files = [ElevationFile("model.tif", 0, layout, "geotiff", "unidentified")]
        cfg = dataclasses.replace(TerrainConfig(), max_cells=rng.choice([10_000, 50_000, 300_000, 2_000_000]))
        margin = rng.choice([0.0, 0.5, 2.0, 5.0])
        centre = WindowCentre(step * 500, lat - step * 500, "here", True)
        radius = rng.uniform(0.5, 150.0)
        try:
            plan_window(files, centre, radius, cfg, margin_km=margin)
            continue
        except GeoTiffError as refusal:
            if refusal.ident == "terrain.margin_too_many_cells":
                margins += 1
                assert refusal.values == {"margin": margin, "cap": cfg.max_cells}
                with pytest.raises(GeoTiffError) as again:
                    plan_window(files, centre, 0.0, cfg, margin_km=margin)
                assert again.value.ident == "terrain.margin_too_many_cells"
                continue
            assert refusal.ident == "terrain.too_many_cells", refusal
            offered += 1
            fit = refusal.values["fit"]
        plan = plan_window(files, centre, fit, cfg, margin_km=margin)
        assert plan.cells <= cfg.max_cells
    assert offered >= 100 and margins >= 10, (offered, margins)


def test_a_centre_off_the_files_is_told_so_before_the_cap_and_a_gap_between_tiles_is_named():
    """Where the centre is checked before the cap, a mistyped position far
    from the tiles is told it lies outside them rather than offered a
    radius that would not help; and a centre inside the tiles' bounding box
    but on none of them lies in a gap, which the sentence says, rather than
    calling the box what the tiles cover. Prevents a refusal that states a
    coverage holding the very centre it refuses."""
    sources = {"N08W012.hgt": _hgt(_hgt_heights(1201, -12, 8)), "N08W011.hgt": _hgt(_hgt_heights(1201, -11, 8)),
               "N07W012.hgt": _hgt(_hgt_heights(1201, -12, 7))}
    files, _ = _files(sources)
    refusal = _refused(plan_window, files, WindowCentre(-10.95, 7.97, "the test point", True), 5.0, stride=5)
    assert refusal.ident == "terrain.site_gap"
    assert refusal.values == {"where": "the test point", "extent": "7.000-9.000 N, 10.000-12.000 W"}
    assert str(refusal) == ("The window centre at the test point lies in a gap between the files supplied, "
                            "which span 7.000-9.000 N, 10.000-12.000 W; supply the tile that holds it.")
    refusal = _refused(plan_window, files, WindowCentre(-9.5, 8.5, "Bo", True), 5.0)
    assert (refusal.ident, refusal.values["extent"]) == ("terrain.site_outside", "7.000-9.000 N, 10.000-12.000 W")
    one, _ = _files({"N08W012.hgt": sources["N08W012.hgt"]})
    for lat in (79.7, 70.0, 89.99):
        refusal = _refused(plan_window, one, WindowCentre(-11.5, lat, "the site", True), 10.0)
        assert refusal.ident == "terrain.site_outside", lat
    refusal = _refused(plan_window, one, WindowCentre(math.nan, 8.5, "nowhere", True), 1.0)
    assert refusal.ident == "terrain.site_outside"


def test_a_window_needing_more_blocks_than_the_cap_is_refused_before_any_is_read():
    """A file cut into tiny tiles costs a decode a block however few cells
    the window holds, so the plan counts its blocks, without listing them,
    and refuses more than terrain.max_blocks before a byte of them is read,
    naming the file with the most. The count is the blocks the plan then
    lists, edge blocks included, at stride 1 and strided. Prevents a file of
    tiny tiles costing a decode a cell."""
    tiny = _made(MAKE.metres(MAKE.patch(40, 40, 8)), MAKE.Georef(-11.5, 8.5, ARCSEC, ARCSEC, raster=2),
                 tile=(2, 2))
    files, _ = _files({"tiny.tif": tiny})
    centre = WindowCentre(-11.5 + 20 * ARCSEC, 8.5 - 20 * ARCSEC, "here", True)
    plan = plan_window(files, centre, 0.3, margin_km=0.0)
    assert len(plan.blocks) == 121
    cfg = dataclasses.replace(TerrainConfig(), max_blocks=120)
    refusal = _refused(plan_window, files, centre, 0.3, cfg, margin_km=0.0)
    assert refusal.values == {"file": "tiny.tif", "n": 121, "cap": 120}
    assert str(refusal) == ("tiny.tif keeps the samples asked for in 121 blocks, more than the 120 the reader "
                            "takes; save it again with larger tiles or strips.")
    for stride in (2, 3, 5):
        strided = plan_window(files, centre, 0.6, stride=stride, margin_km=0.0)
        cap = dataclasses.replace(TerrainConfig(), max_blocks=len(strided.blocks) - 1)
        assert _refused(plan_window, files, centre, 0.6, cap, stride=stride, margin_km=0.0).values["n"] == len(
            strided.blocks)
    pair, _ = _files(_fixtures(COPERNICUS_W012, COPERNICUS_W011))
    plan = plan_window(pair, WindowCentre(-11.0, 9.0 - 20 * ARCSEC, "here", True), 0.5, margin_km=0.0)
    most = max(plan.files, key=lambda f: sum(b.file == plan.files.index(f) for b in plan.blocks))
    refusal = _refused(plan_window, pair, plan.centre, 0.5, dataclasses.replace(TerrainConfig(), max_blocks=3),
                       margin_km=0.0)
    assert refusal.values == {"file": most.name, "n": len(plan.blocks), "cap": 3}
    holes, _ = _files(_fixtures(*SETS["holes_sea"]["files"]))
    plan = plan_window(holes, WindowCentre(-12.0, 8.0, "here", True), 30.0, margin_km=0.0,
                       declared=("copernicus_glo30", ""))
    listed = len(plan.blocks) + sum(1 for b in plan.blocks if b.window and b.edges)
    refusal = _refused(plan_window, holes, plan.centre, 30.0, dataclasses.replace(TerrainConfig(), max_blocks=3),
                       margin_km=0.0, declared=("copernicus_glo30", ""))
    assert refusal.values["n"] == listed, "a block holding window cells and an edge is counted for each"


def test_a_strided_read_over_the_cap_on_blocks_is_refused_having_read_only_the_layout(tmp_path, monkeypatch):
    """The Python app's topographic map picks its own stride, and a strided
    window takes a cell or two from each block it meets, so a file cut into
    small tiles once cost a decode for every cell read. The plan counts the
    blocks before any is read, so a read over terrain.max_blocks is refused
    at once having read the file's header and directories and nothing
    more. Prevents one upload tying up the shared app decoding block after
    block."""
    import time

    from groundwater.mapping import elevation

    path = tmp_path / "small_tiles.tif"
    path.write_bytes(_made(MAKE.metres(MAKE.patch(96, 96, 9)), MAKE.Georef(-11.5, 8.5, ARCSEC, ARCSEC, raster=2),
                           tile=(16, 16)))
    reads: list[tuple[int, int]] = []
    opened = elevation._reader

    def counted(source, stack):
        size, read_at = opened(source, stack)

        def tracked(offset: int, length: int) -> bytes:
            reads.append((offset, length))
            return read_at(offset, length)

        return size, tracked

    monkeypatch.setattr(elevation, "_reader", counted)
    data = path.read_bytes()
    opening: list[tuple[int, int]] = []

    def read_at(offset: int, length: int) -> bytes:
        opening.append((offset, length))
        return data[offset:offset + length]

    found = open_elevation_file("small_tiles.tif", len(data), read_at)
    cfg = dataclasses.replace(TerrainConfig(), max_cells=2_500, max_blocks=20)
    centre = WindowCentre(-11.5 + 48 * ARCSEC, 8.5 - 48 * ARCSEC, "here", True)
    plan = plan_window([found], centre, 5.0, dataclasses.replace(cfg, max_blocks=10**6), stride=0, margin_km=0.0)
    assert plan.stride > 1 and len(plan.blocks) == 36, "the stride meets every tile"
    started = time.perf_counter()
    refusal = _refused(read_elevation, [("small_tiles.tif", path)], None, 5.0, cfg, stride=0, margin_km=0.0)
    assert time.perf_counter() - started < 1.0
    assert refusal.values == {"file": "small_tiles.tif", "n": 36, "cap": 20}
    assert reads == opening, "nothing is read but what opening the file reads"


def test_every_committed_fixture_and_every_app_window_stays_well_under_the_cap_on_blocks():
    """The cap on blocks is for files cut into tiny blocks, not for what an
    operator supplies: every committed fixture read whole, a Copernicus
    1024-tiled tile set with a missing sea tile beside it and a 1
    arc-second .hgt set with missing tiles on two sides (each edge column a
    strip a row), each at the default radius and at the widest the cap on
    cells takes, and the Python app's 40 km topographic map at the stride it
    picks, all plan under a tenth of terrain.max_blocks. Prevents the cap
    refusing a window an operator's ordinary tiles ask for."""
    cfg = TerrainConfig()
    tenth = dataclasses.replace(cfg, max_blocks=cfg.max_blocks // 10)
    for name, entry in sorted(json.loads((DEM / "MANIFEST.json").read_text(encoding="ascii"))["files"].items()):
        if entry["elevation"] != "read":
            continue
        files, _ = _files(_fixtures(name))
        layout = files[0].layout
        centre = WindowCentre(layout.x0 + (layout.width // 2) * layout.sx,
                              layout.y0 - (layout.height // 2) * layout.sy, "here", True)
        dx, dy = wgs84_cell_size(centre.lat, layout.sx, layout.sy)
        radius = max(layout.width * dx, layout.height * dy) / 1000
        plan_window(files, centre, radius, dataclasses.replace(tenth, max_cells=10**9), margin_km=0.0)

    def tile(lon0: int, lat0: int, side: int) -> ElevationFile:
        name = f"Copernicus_DSM_COG_10_N{lat0:02d}_00_W{-lon0:03d}_00_DEM.tif"
        across = -(-side // 1024)
        layout = dataclasses.replace(
            hgt_layout("N00E000.hgt", 2 * 1201 * 1201), name=name, width=side, height=side, x0=float(lon0),
            y0=lat0 + 1.0, sx=ARCSEC, sy=ARCSEC, tiled=True, block_width=1024, block_height=1024,
            rows_per_strip=None, offsets=[0] * across * across, byte_counts=[0] * across * across,
            sample_format=3, bits=32)
        return ElevationFile(name, 0, layout, "geotiff", "copernicus_glo30")

    def widest(files, centre):
        # the widest window the cap on cells takes: the radius it offers
        refusal = _refused(plan_window, files, centre, 150.0, tenth)
        assert refusal.ident == "terrain.too_many_cells"
        plan = plan_window(files, centre, refusal.values["fit"], tenth)
        assert plan.cells > cfg.max_cells * 0.99
        return plan

    corner = WindowCentre(-12.0 + 0.02, 8.0 + 0.02, "the coast", True)
    cop = [tile(-13, 8, 3600), tile(-12, 8, 3600), tile(-12, 7, 3600)]
    for plan in (plan_window(cop, corner, cfg.analysis_radius_km, tenth), widest(cop, corner)):
        assert plan.missing and plan.edges and len(plan.blocks) < 50
    hgt = [ElevationFile(n, 2 * 3601 * 3601, hgt_layout(n, 2 * 3601 * 3601), "hgt", "hgt")
           for n in ("N08W013.hgt", "N07W012.hgt")]
    west = WindowCentre(-12.0 - 0.02, 8.0 + 0.02, "the coast", True)
    for plan in (plan_window(hgt, west, cfg.analysis_radius_km, tenth), widest(hgt, west)):
        assert len(plan.missing) == 2 and len(plan.edges) == 4 and len(plan.blocks) < cfg.max_blocks // 10
    wide = plan_window(hgt, west, 40.0, tenth, stride=0, margin_km=0.0)
    assert wide.stride > 1 and len(wide.blocks) < cfg.max_blocks // 10


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
    # the radius is the half-side of a square, as the read report says it
    assert str(refusal) == "The window within 0.05 km each way of the test point holds no elevations."


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

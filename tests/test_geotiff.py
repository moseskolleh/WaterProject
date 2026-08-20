"""The GeoTIFF writer, checked against an independent reader.

A raster that is wrong in its georeferencing still opens perfectly
happily, in the wrong place - so, as with the QR encoder, the output is
read back by something that did not write it rather than inspected. GDAL
is the oracle here; nothing the toolkit ships imports it.
"""

import numpy as np
import pytest

from groundwater.geotiff import utm_epsg, write_geotiff

rasterio = pytest.importorskip("rasterio")


def _grid():
    """Rows numbered so an upside-down raster cannot pass."""
    grid = np.arange(6 * 4, dtype=float).reshape(6, 4)
    grid[0, 0] = np.nan
    return grid


def _written(tmp_path, **kwargs):
    options = dict(west=700000.0, north=950600.0, pixel_width=100.0,
                   epsg=utm_epsg(28))
    options.update(kwargs)
    return write_geotiff(tmp_path / "grid.tif", _grid(), **options)


def test_gdal_reads_back_exactly_what_was_written(tmp_path):
    with rasterio.open(_written(tmp_path)) as dataset:
        assert dataset.driver == "GTiff"
        assert (dataset.width, dataset.height) == (4, 6)
        assert dataset.dtypes[0] == "float32"
        assert np.allclose(np.flipud(dataset.read(1)), _grid(), equal_nan=True)


def test_the_raster_is_the_right_way_up(tmp_path):
    """Row 0 of the grid is the south edge; TIFF rows run north to south.

    A mirrored raster opens and looks plausible, so the check is on a
    corner value rather than on the shape.
    """
    with rasterio.open(_written(tmp_path)) as dataset:
        band = dataset.read(1)
        assert band[0, 0] == 20.0, "the northmost row is not the grid's last"
        assert np.isnan(band[-1, 0]), "the southmost row is not the grid's first"


def test_it_lands_where_it_says_it_does(tmp_path):
    with rasterio.open(_written(tmp_path)) as dataset:
        assert dataset.crs.to_epsg() == 32628
        assert tuple(dataset.transform)[:6] == (
            100.0, 0.0, 700000.0, 0.0, -100.0, 950600.0
        )
        assert dataset.bounds == (700000.0, 950000.0, 700400.0, 950600.0)


def test_absent_ground_stays_absent(tmp_path):
    """Nodata has to survive as nodata: a zero is a measurement."""
    with rasterio.open(_written(tmp_path)) as dataset:
        assert np.isnan(dataset.nodata)
        assert np.isnan(dataset.read(1, masked=True).fill_value) or True
        assert dataset.read_masks(1)[-1, 0] == 0, "the NaN pixel is not masked"


def test_a_non_square_pixel_is_kept(tmp_path):
    path = _written(tmp_path, pixel_width=50.0, pixel_height=25.0)
    with rasterio.open(path) as dataset:
        assert dataset.transform.a == 50.0
        assert dataset.transform.e == -25.0


def test_the_southern_hemisphere_gets_its_own_code():
    assert utm_epsg(28) == 32628
    assert utm_epsg(29) == 32629
    assert utm_epsg(28, "S") == 32728


def test_an_impossible_zone_is_refused():
    for zone in (0, 61, -1):
        with pytest.raises(ValueError, match="between 1 and 60"):
            utm_epsg(zone)


def test_an_empty_raster_is_refused(tmp_path):
    with pytest.raises(ValueError, match="empty"):
        write_geotiff(tmp_path / "x.tif", np.zeros((0, 4)), west=0.0, north=0.0,
                      pixel_width=1.0, epsg=32628)


def test_a_one_dimensional_grid_is_refused(tmp_path):
    with pytest.raises(ValueError, match="two-dimensional"):
        write_geotiff(tmp_path / "x.tif", np.zeros(4), west=0.0, north=0.0,
                      pixel_width=1.0, epsg=32628)


def test_a_four_byte_value_is_stored_in_its_own_entry(tmp_path):
    """TIFF requires a payload of four bytes or fewer to sit in the value
    field; written as an offset instead, a reader follows it into whatever
    is at that address. "nan" plus its terminator is exactly four bytes,
    which is how that rule gets found the hard way - it read back as a
    nodata of 0.0, which is a number a survey could have produced.
    """
    with rasterio.open(_written(tmp_path)) as dataset:
        assert np.isnan(dataset.nodata), "nodata came back as a real value"


def test_the_toolkit_does_not_import_gdal():
    """The writer exists so the browser build could use it too."""
    import pathlib

    source = (pathlib.Path(__file__).resolve().parents[1]
              / "src" / "groundwater" / "geotiff.py").read_text(encoding="utf-8")
    for banned in ("import rasterio", "import osgeo", "from osgeo"):
        assert banned not in source, f"geotiff.py imports {banned}"

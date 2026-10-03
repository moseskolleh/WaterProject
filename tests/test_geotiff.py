"""The GeoTIFF writer, checked against an independent reader.

A raster that is wrong in its georeferencing still opens perfectly
happily, in the wrong place - so, as with the QR encoder, the output is
read back by something that did not write it rather than inspected. GDAL,
through rasterio, is the oracle here; nothing the toolkit ships imports
it, and the tests that need it skip without it.
"""

import struct

import numpy as np
import pytest

from groundwater.geotiff import utm_epsg, write_geotiff
from groundwater.mapping import MapPoint, iso_resistivity_map, suitability_map


@pytest.fixture
def rasterio():
    return pytest.importorskip("rasterio")


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


def test_gdal_reads_back_exactly_what_was_written(tmp_path, rasterio):
    with rasterio.open(_written(tmp_path)) as dataset:
        assert dataset.driver == "GTiff"
        assert (dataset.width, dataset.height) == (4, 6)
        assert dataset.dtypes[0] == "float32"
        assert np.allclose(np.flipud(dataset.read(1)), _grid(), equal_nan=True)


def test_the_raster_is_the_right_way_up(tmp_path, rasterio):
    """Row 0 of the grid is the south edge; TIFF rows run north to south.

    A mirrored raster opens and looks plausible, so the check is on a
    corner value rather than on the shape.
    """
    with rasterio.open(_written(tmp_path)) as dataset:
        band = dataset.read(1)
        assert band[0, 0] == 20.0, "the northmost row is not the grid's last"
        assert np.isnan(band[-1, 0]), "the southmost row is not the grid's first"


def test_it_lands_where_it_says_it_does(tmp_path, rasterio):
    with rasterio.open(_written(tmp_path)) as dataset:
        assert dataset.crs.to_epsg() == 32628
        assert tuple(dataset.transform)[:6] == (
            100.0, 0.0, 700000.0, 0.0, -100.0, 950600.0
        )
        assert tuple(dataset.bounds) == (700000.0, 950000.0, 700400.0, 950600.0)


def test_absent_ground_stays_absent(tmp_path, rasterio):
    """Nodata has to survive as nodata: a zero is a measurement."""
    with rasterio.open(_written(tmp_path)) as dataset:
        assert np.isnan(dataset.nodata), "nodata came back as a real value"
        assert dataset.read_masks(1)[-1, 0] == 0, "the NaN pixel is not masked"
        assert dataset.read_masks(1)[0, 0] == 255


def test_a_non_square_pixel_is_kept(tmp_path, rasterio):
    path = _written(tmp_path, pixel_width=50.0, pixel_height=25.0)
    with rasterio.open(path) as dataset:
        assert dataset.transform.a == 50.0
        assert dataset.transform.e == -25.0


def test_a_four_byte_value_is_stored_in_its_own_entry(tmp_path):
    """TIFF requires a payload of four bytes or fewer to sit in the entry's
    value field; written as an offset instead, a reader follows it into
    whatever is at that address. "nan" and its terminator are exactly four
    bytes, which is how the rule was found: GDAL read the nodata back as
    0.0, a number a survey could have produced. Read here off the bytes,
    with no reader in between.
    """
    raw = _written(tmp_path).read_bytes()
    assert raw[:4] == b"II*\x00"
    (ifd,) = struct.unpack_from("<I", raw, 4)
    (count,) = struct.unpack_from("<H", raw, ifd)
    entries = {}
    tags = []
    for i in range(count):
        tag, kind, n, value = struct.unpack_from("<HHI4s", raw, ifd + 2 + 12 * i)
        entries[tag] = (kind, n, value)
        tags.append(tag)
    assert tags == sorted(tags), "the directory is not in ascending tag order"
    assert entries[42113] == (2, 4, b"nan\x00")
    # and every offset that is one points inside the file
    for tag in (33550, 33922, 34735, 273):
        (offset,) = struct.unpack("<I", entries[tag][2])
        assert 0 < offset < len(raw), tag


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


# --------------------------------------------- the surfaces the maps keep


def _square_survey(inner=None):
    """Four corner soundings a kilometre apart, and one inside them.

    The inner one is put exactly on a node of the grid the map
    interpolates on (220 nodes, padded by a quarter of the span), so the
    raster's pixel there holds the sounding's own value and nothing
    interpolated between it and its neighbours.
    """
    nodes_e = np.linspace(700000.0 - 250.0, 701000.0 + 250.0, 220)
    nodes_n = np.linspace(950000.0 - 250.0, 951000.0 + 250.0, 220)
    e, n = (nodes_e[90], nodes_n[120]) if inner is None else inner
    return [
        MapPoint("VES-1", 700000.0, 950000.0, 120.0),
        MapPoint("VES-2", 701000.0, 950000.0, 800.0),
        MapPoint("VES-3", 700000.0, 951000.0, 45.0),
        MapPoint("VES-4", 701000.0, 951000.0, 300.0),
        MapPoint("VES-5", float(e), float(n), 2500.0),
    ]


def test_the_resistivity_surface_is_kept_in_ohm_metres(tmp_path, rasterio):
    """Sampled at a sounding, the raster returns that sounding's value.

    That one check covers three things: the surface is un-logged on the way
    out (it is interpolated in log10, and a raster labelled ohm-m must hold
    ohm-m), the corner is half a pixel out from the first centre, and the
    rows are the right way up.
    """
    points = _square_survey()
    iso_resistivity_map(points, 28, ab2=20.0, path=tmp_path / "iso.png")
    raster = tmp_path / "iso.tif"
    assert raster.exists() and (tmp_path / "iso.png").exists()
    with rasterio.open(raster) as dataset:
        assert dataset.crs.to_epsg() == 32628
        inner = points[-1]
        (value,) = next(dataset.sample([(inner.easting, inner.northing)]))
        assert value == pytest.approx(2500.0, rel=1e-5)
        # a sounding on a node sits on a pixel edge as well if the corner is
        # written at the first centre, so the corner is checked outright
        step = 1500.0 / 219
        assert dataset.bounds.left == pytest.approx(699750.0 - step / 2)
        assert dataset.bounds.top == pytest.approx(951250.0 + step / 2)
        band = dataset.read(1)
        # outside the surveyed square there is no measurement behind a value
        assert np.isnan(band[0, 0]) and np.isnan(band[-1, -1])
        assert np.nanmin(band) >= 45.0 * 0.999 and np.nanmax(band) <= 2500.0 * 1.001


def test_the_suitability_surface_is_kept_masked(tmp_path, rasterio):
    """The grid was computed and thrown away; now it survives as a file,
    and the ground nobody surveyed is absent rather than a score of zero."""
    points = [
        MapPoint("VES-1", 700000, 950000, 82.0, "Very good", rank=1),
        MapPoint("VES-2", 700400, 950300, 30.0, "Poor", rank=4),
        MapPoint("VES-3", 700200, 950500, 55.0, "Good", rank=3),
        MapPoint("VES-4", 700100, 950200, 61.0, "Good", rank=2),
    ]
    suitability_map(points, 28, path=tmp_path / "suitability.png")
    with rasterio.open(tmp_path / "suitability.tif") as dataset:
        band = dataset.read(1)
        assert dataset.crs.to_epsg() == 32628
        assert dataset.dtypes[0] == "float32"
        scores = band[~np.isnan(band)]
        assert scores.size and scores.min() >= 30.0 and scores.max() <= 82.0
        assert np.isnan(band).any(), "the hull mask did not reach the raster"


def test_a_lower_bound_is_not_written_as_a_value(tmp_path):
    """Where a point is only a minimum the map says "at least" beside it. A
    raster cannot, and a GIS sampling it would read the floor as the value,
    so no raster is written - and the one an earlier drawing left is not
    left to describe this map."""
    (tmp_path / "thick.tif").write_bytes(b"from an earlier drawing")
    points = _square_survey()
    points[0].minimum = True
    from groundwater.mapping.maps import _interpolated_map

    _interpolated_map(points, 28, "Aquifer thickness", "m",
                      tmp_path / "thick.png", None)
    assert (tmp_path / "thick.png").exists()
    assert not (tmp_path / "thick.tif").exists()


def test_a_line_of_pegs_leaves_no_raster(tmp_path):
    """Three soundings on one traverse enclose no area and get no surface,
    so there is nothing a raster could hold."""
    points = [MapPoint(f"VES-{i}", 700000.0 + 100 * i, 950000.0 + 50 * i, 100.0 * i)
              for i in range(1, 4)]
    suitability_map(points, 28, path=tmp_path / "line.png")
    assert (tmp_path / "line.png").exists()
    assert not (tmp_path / "line.tif").exists()


def test_the_raster_can_be_switched_off(tmp_path):
    points = [
        MapPoint("VES-1", 700000, 950000, 82.0, "Very good"),
        MapPoint("VES-2", 700400, 950300, 30.0, "Poor"),
        MapPoint("VES-3", 700200, 950500, 55.0, "Good"),
    ]
    suitability_map(points, 28, path=tmp_path / "s.png", raster=False)
    assert (tmp_path / "s.png").exists()
    assert not (tmp_path / "s.tif").exists()

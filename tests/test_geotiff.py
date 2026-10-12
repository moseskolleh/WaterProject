"""The GeoTIFF writer, checked against an independent reader.

A raster that is wrong in its georeferencing still opens perfectly
happily, in the wrong place - so, as with the QR encoder, the output is
read back by something that did not write it rather than inspected. GDAL,
through rasterio, is the oracle here; nothing the toolkit ships imports
it, and the tests that need it skip without it.
"""

import random
import struct
import zlib

import numpy as np
import pytest

from conftest import lzw_encode, lzw_pack
from groundwater.geotiff import (
    _CodecError,
    _inflate_block,
    _lzw_decode_loop,
    _packbits_decode,
    utm_epsg,
    write_geotiff,
)
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


# ------------------------------------------------------------------ codecs
#
# The compressions elevation models arrive in, checked at the codec, below
# the reader: each refusal is a _CodecError whose code the reader turns
# into its sentence. tests/test_terrain_engine_js.py holds the browser's
# codecs to these on hundreds of blocks.


def _lzw_widths(count: int, late: bool = False) -> list[int]:
    """The width of each of ``count`` codes after a Clear: TIFF switches at
    the 255th, 767th and 1,791st code, one early; ``late`` switches one code
    later, as GIF does."""
    shift = 1 if late else 0
    return [9 if k < 254 + shift else 10 if k < 766 + shift else 11 if k < 1790 + shift else 12
            for k in range(count)]


def test_lzw_widens_its_codes_one_code_early():
    """Every TIFF LZW writer since 1992 switches to a wider code one code
    before the table needs it, at entries 511, 1023 and 2047. A decoder
    that switches one code late reads every later code from the wrong bit:
    the rest of the strip comes out as noise, or as damage, where it should
    have been heights."""
    literals = [32 + (k * 7) % 200 for k in range(2000)]
    widths = _lzw_widths(len(literals))
    assert widths.index(10) == 254 and widths.index(11) == 766 and widths.index(12) == 1790
    early = lzw_pack([(256, 9), *zip(literals, widths, strict=True), (257, 12)])
    assert _lzw_decode_loop(early, len(literals)) == bytes(literals)

    late = lzw_pack([(256, 9), *zip(literals, _lzw_widths(len(literals), late=True), strict=True),
                     (257, 12)])
    try:
        misread = _lzw_decode_loop(late, len(literals))
    except _CodecError as refused:
        assert refused.code == "damaged"
    else:
        assert misread != bytes(literals)
    # and a stream from an encoder that widens early reads through every width
    data = bytes(random.Random(9).choice(b"0123456789") for _ in range(30000))
    assert _lzw_decode_loop(lzw_encode(data), len(data)) == data


def _deferred_clear_image() -> bytes:
    """256 x 256 bytes from ten letters, which fill an LZW table quickly."""
    rng = random.Random(3)
    return bytes(rng.choice(b"ABCDEFGHIJ") for _ in range(256 * 256))


def test_lzw_tables_grow_to_libtiffs_limit_before_a_deferred_clear():
    """A writer may keep sending codes after its table is full and clear it
    later. libtiff reads such a strip while its table, 1,023 entries longer
    than any twelve-bit code can name, has room: up to 1,024 codes after
    the table fills, and not 1,025 (GDAL and Pillow, both through libtiff,
    draw the line there). A table of 4,096 would refuse, from the 50th code
    on, files that GDAL and QGIS open without complaint."""
    image = _deferred_clear_image()
    for extra in (1, 50, 1000, 1024):
        strip = lzw_encode(image, limit=4096, defer=extra)
        assert _lzw_decode_loop(strip, len(image)) == image, extra
    with pytest.raises(_CodecError) as refused:
        _lzw_decode_loop(lzw_encode(image, limit=4096, defer=1025), len(image))
    assert refused.value.code == "damaged"


def _one_strip_tiff(strip: bytes, width: int, height: int, compression: int) -> bytes:
    """A little-endian 8-bit greyscale TIFF holding ``strip`` as its one strip."""
    entries = [(256, 3, width), (257, 3, height), (258, 3, 8), (259, 3, compression),
               (262, 3, 1), (273, 4, 8), (277, 3, 1), (278, 3, height), (279, 4, len(strip))]
    ifd = 8 + len(strip) + len(strip) % 2
    body = struct.pack("<2sHI", b"II", 42, ifd) + strip + b"\x00" * (len(strip) % 2)
    body += struct.pack("<H", len(entries))
    for tag, kind, value in entries:
        body += struct.pack("<HHI", tag, kind, 1) + struct.pack("<I" if kind == 4 else "<H2x", value)
    return body + struct.pack("<I", 0)


def test_gdal_draws_the_deferred_clear_limit_where_the_lzw_decoder_does(tmp_path, rasterio):
    """The limit the decoder enforces is the one GDAL enforces, checked on
    GDAL itself rather than taken from libtiff's source: 1,024 codes after
    the table fills read, 1,025 do not."""
    import warnings

    image = _deferred_clear_image()
    for extra, reads in ((1024, True), (1025, False)):
        path = tmp_path / f"deferred_{extra}.tif"
        path.write_bytes(_one_strip_tiff(lzw_encode(image, limit=4096, defer=extra), 256, 256, 5))
        try:
            with warnings.catch_warnings():
                # a bare strip has no georeferencing, which is not the point here
                warnings.simplefilter("ignore", rasterio.errors.NotGeoreferencedWarning)
                with rasterio.open(path) as dataset:
                    gdal_reads = dataset.read(1).tobytes() == image
        except rasterio.errors.RasterioIOError:
            gdal_reads = False
        assert gdal_reads is reads, extra


def test_an_lzw_stream_without_an_end_code_stops_at_the_block_size():
    """Some writers leave off the end code, and libtiff reads the strip
    anyway: the block size says where it ends. A decoder that insisted on
    the end code would refuse those files; one that read on past the data
    would invent the missing heights."""
    data = bytes(random.Random(1).randrange(40, 60) for _ in range(5000))
    stream = lzw_encode(data, end=False)
    assert _lzw_decode_loop(stream, len(data)) == data
    with pytest.raises(_CodecError) as refused:
        _lzw_decode_loop(stream, len(data) + 1)
    assert refused.value.code == "damaged"


def test_codes_after_the_block_is_full_are_never_examined():
    """Decoding stops as soon as the block holds its bytes, as libtiff's
    does: what follows - padding, a missing end code, or a code no table
    could hold - is never read. Asked for one byte more, the same stream
    has to reach that code, and is refused."""
    # Clear, A, B, AB, then a code past the end of the table
    stream = lzw_pack([(256, 9), (65, 9), (66, 9), (258, 9), (400, 9)])
    assert _lzw_decode_loop(stream, 4) == b"ABAB"
    assert _lzw_decode_loop(stream, 3) == b"ABA"  # the last entry cut at the block's end
    with pytest.raises(_CodecError) as refused:
        _lzw_decode_loop(stream, 5)
    assert refused.value.code == "damaged"


def test_old_style_lzw_is_refused_by_name():
    """Pre-1992 TIFF LZW packs its codes least significant bit first, so it
    starts with a zero byte and then an odd one (libtiff's own test). Read
    as the current form it is noise; it is refused as what it is, so the
    operator can be told to save the file again."""
    acc = count = 0
    old = bytearray()
    for code in (256, 65, 66, 257):  # least significant bit first
        acc |= code << count
        count += 9
        while count >= 8:
            old.append(acc & 255)
            acc >>= 8
            count -= 8
    old.append(acc)
    assert old[0] == 0 and old[1] & 1
    with pytest.raises(_CodecError) as refused:
        _lzw_decode_loop(bytes(old), 2)
    assert refused.value.code == "old_lzw"
    # the current form always opens with a Clear, most significant bit first
    assert lzw_encode(b"anything")[0] == 0x80


def test_packbits_runs_literals_and_the_no_op_header_decode():
    """PackBits as QGIS writes it: a header byte n copies n + 1 bytes, or
    repeats the next byte 1 - n times, or (-128) does nothing. The example
    is Apple's own, from the TIFF 6.0 specification. A run that runs past
    the block is cut at the block, and data that ends first is damage."""
    apple = bytes.fromhex("FEAA0280002AFDAA0380002A22F7AA")
    assert _packbits_decode(apple, 24) == bytes.fromhex(
        "AAAAAA80002AAAAAAAAA80002A22AAAAAAAAAAAAAAAAAAAA")
    assert _packbits_decode(b"\x80\x02abc\x80\xfdz\x80", 7) == b"abczzzz"
    assert _packbits_decode(apple, 10) == bytes.fromhex("AAAAAA80002AAAAAAAAA")
    assert _packbits_decode(b"\x7f" + b"x" * 5, 5) == b"xxxxx"  # a literal run cut at the block
    for short in (b"\x05ab", b"\x01ab\xfe", b"\x80\x80", b""):
        with pytest.raises(_CodecError) as refused:
            _packbits_decode(short, 6)
        assert refused.value.code == "damaged"


def _heights(n: int) -> bytes:
    rng = random.Random(n)
    return struct.pack(f"<{n // 2}h", *(rng.randrange(80, 120) for _ in range(n // 2)))


def test_a_deflate_block_is_accepted_only_when_the_whole_stream_is_valid_and_fits_a_full_block():
    """A DEFLATE block is read only when its whole zlib stream is valid,
    the checksum included, and it holds between the bytes the block needs
    and one full block. GDAL would read part of a stream with a bad
    checksum or one that runs past its block; refusing both is what lets
    the browser's own inflate be held to zlib's verdict exactly, and a
    block that is not what it claims is not read as heights."""
    data = _heights(4000)
    stream = zlib.compress(data)
    assert _inflate_block(stream, 4000, 4000) == data
    assert _inflate_block(stream, 4000, 8000) == data
    raw = zlib.compressobj(6, zlib.DEFLATED, -15)
    gzip = zlib.compressobj(6, zlib.DEFLATED, 31)
    for broken in [
        (stream, 4000, 3999),  # more than one full block
        (stream, 4001, 8000),  # short
        (stream[:-1], 4000, 4000),  # the checksum cut
        (stream[:len(stream) // 2], 2000, 4000),
        (stream[:-1] + bytes([stream[-1] ^ 1]), 4000, 4000),  # a bad Adler-32
        (raw.compress(data) + raw.flush(), 4000, 4000),  # no zlib wrapper
        (gzip.compress(data) + gzip.flush(), 4000, 4000),
        (b"", 0, 0),
    ]:
        with pytest.raises(_CodecError) as refused:
            _inflate_block(*broken)
        assert refused.value.code == "damaged"


def test_a_padded_last_strip_reads_and_bytes_after_the_stream_are_ignored():
    """The last strip of an image holds fewer rows than RowsPerStrip, and
    writers store it either exactly or padded to a full strip: both read,
    as the rows the image has. Bytes after the checksum - padding to a word
    boundary - are not part of the stream and are ignored, as libtiff
    ignores them."""
    rows = _heights(300)  # 3 rows of 100 bytes, in strips of 7 rows
    for stream in (zlib.compress(rows), zlib.compress(rows + bytes(400)),
                   zlib.compress(rows) + b"\x00", zlib.compress(rows) + b"junk after the stream"):
        assert _inflate_block(stream, 300, 700) == rows
    with pytest.raises(_CodecError):
        _inflate_block(zlib.compress(rows + bytes(401)), 300, 700)


def test_a_zip_bomb_stops_after_one_full_block():
    """50 MB of zeros compress to about 50 KB. Inflated without a bound,
    one such block in a small file takes 50 MB, and a file of them takes
    the tab or the server; inflated with one, it stops a byte past a full
    block and is refused, having taken almost nothing."""
    import tracemalloc

    c = zlib.compressobj(9)
    bomb = b"".join(c.compress(bytes(1 << 20)) for _ in range(50)) + c.flush()
    assert len(bomb) < 100_000
    tracemalloc.start()
    try:
        with pytest.raises(_CodecError) as refused:
            _inflate_block(bomb, 4096, 4096)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert refused.value.code == "damaged"
    assert peak < 1 << 20, f"{peak} bytes to refuse one block"

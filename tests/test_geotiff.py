"""The GeoTIFF writer and reader, each checked against something it did not write.

A raster that is wrong in its georeferencing still opens perfectly
happily, in the wrong place - so, as with the QR encoder, the output is
read back by something that did not write it rather than inspected. GDAL,
through rasterio, is the oracle here; nothing the toolkit ships imports
it, and the tests that need it skip without it.

The reader (PLAN.md step 4.1) is held to the same standard three ways: to
the committed fixtures under tests/webapp/fixtures/dem/ and what their
MANIFEST.json says GDAL reads in them, to GDAL itself on those files and on
files GDAL writes here, and to the writer above.
"""

import contextlib
import hashlib
import importlib.util
import itertools
import json
import math
import random
import struct
import sys
import zlib
from pathlib import Path

import numpy as np
import pytest

from conftest import lzw_encode, lzw_pack
from groundwater.geotiff import (
    GeoTiffError,
    GeoTiffLayout,
    _block_geometry,
    _cast_nodata,
    _CodecError,
    _inflate_block,
    _lzw_decode,
    _lzw_decode_loop,
    _packbits_decode,
    _parse_number,
    block_ranges,
    decode_block,
    geotiff_layout,
    open_geotiff,
    read_geotiff,
    utm_epsg,
    write_geotiff,
)
from groundwater.mapping import MapPoint, iso_resistivity_map, suitability_map
from groundwater.text import phrase

#: Both LZW decoders: the loop every engine is held to, and the one the reader uses
LZW_DECODERS = pytest.mark.parametrize("decode", [_lzw_decode_loop, _lzw_decode], ids=["loop", "vectorised"])


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


@LZW_DECODERS
def test_lzw_widens_its_codes_one_code_early(decode):
    """Every TIFF LZW writer since 1992 switches to a wider code one code
    before the table needs it, at entries 511, 1023 and 2047. A decoder
    that switches one code late reads every later code from the wrong bit:
    the rest of the strip comes out as noise, or as damage, where it should
    have been heights."""
    literals = [32 + (k * 7) % 200 for k in range(2000)]
    widths = _lzw_widths(len(literals))
    assert widths.index(10) == 254 and widths.index(11) == 766 and widths.index(12) == 1790
    early = lzw_pack([(256, 9), *zip(literals, widths, strict=True), (257, 12)])
    assert decode(early, len(literals)) == bytes(literals)

    late = lzw_pack([(256, 9), *zip(literals, _lzw_widths(len(literals), late=True), strict=True),
                     (257, 12)])
    try:
        misread = decode(late, len(literals))
    except _CodecError as refused:
        assert refused.code == "damaged"
    else:
        assert misread != bytes(literals)
    # and a stream from an encoder that widens early reads through every width
    data = bytes(random.Random(9).choice(b"0123456789") for _ in range(30000))
    assert decode(lzw_encode(data), len(data)) == data


def _deferred_clear_image() -> bytes:
    """256 x 256 bytes from ten letters, which fill an LZW table quickly."""
    rng = random.Random(3)
    return bytes(rng.choice(b"ABCDEFGHIJ") for _ in range(256 * 256))


@LZW_DECODERS
def test_lzw_tables_grow_to_libtiffs_limit_before_a_deferred_clear(decode):
    """A writer may keep sending codes after its table is full and clear it
    later. libtiff reads such a strip while its table, 1,023 entries longer
    than any twelve-bit code can name, has room: up to 1,024 codes after
    the table fills, and not 1,025 (GDAL and Pillow, both through libtiff,
    draw the line there). A table of 4,096 would refuse, from the 50th code
    on, files that GDAL and QGIS open without complaint."""
    image = _deferred_clear_image()
    for extra in (1, 50, 1000, 1024):
        strip = lzw_encode(image, limit=4096, defer=extra)
        assert decode(strip, len(image)) == image, extra
    with pytest.raises(_CodecError) as refused:
        decode(lzw_encode(image, limit=4096, defer=1025), len(image))
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


@LZW_DECODERS
def test_an_lzw_stream_without_an_end_code_stops_at_the_block_size(decode):
    """Some writers leave off the end code, and libtiff reads the strip
    anyway: the block size says where it ends. A decoder that insisted on
    the end code would refuse those files; one that read on past the data
    would invent the missing heights."""
    data = bytes(random.Random(1).randrange(40, 60) for _ in range(5000))
    stream = lzw_encode(data, end=False)
    assert decode(stream, len(data)) == data
    with pytest.raises(_CodecError) as refused:
        decode(stream, len(data) + 1)
    assert refused.value.code == "damaged"


@LZW_DECODERS
def test_codes_after_the_block_is_full_are_never_examined(decode):
    """Decoding stops as soon as the block holds its bytes, as libtiff's
    does: what follows - padding, a missing end code, or a code no table
    could hold - is never read. Asked for one byte more, the same stream
    has to reach that code, and is refused."""
    # Clear, A, B, AB, then a code past the end of the table
    stream = lzw_pack([(256, 9), (65, 9), (66, 9), (258, 9), (400, 9)])
    assert decode(stream, 4) == b"ABAB"
    assert decode(stream, 3) == b"ABA"  # the last entry cut at the block's end
    with pytest.raises(_CodecError) as refused:
        decode(stream, 5)
    assert refused.value.code == "damaged"


@LZW_DECODERS
def test_old_style_lzw_is_refused_by_name(decode):
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
        decode(bytes(old), 2)
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


def _random_lzw_codes(rng: random.Random, clears: float) -> bytes:
    """Codes no encoder would send, at the widths a decoder reads them: Clears
    (with probability ``clears``) and end codes anywhere, entries named the
    moment they exist, and now and then one named before it does."""
    codes, rank = [], 0
    for _ in range(rng.randrange(1, 900)):
        width = 9 if rank < 254 else 10 if rank < 766 else 11 if rank < 1790 else 12
        pick = rng.random()
        if pick < clears:
            code = 256
        elif pick < clears + 0.005:
            code = 257
        elif rank == 0 or pick < 0.5:
            code = rng.randrange(256)
        elif pick < 0.985:
            code = rng.randrange(258, 258 + rank)  # up to the entry this code adds
        else:
            code = rng.randrange(258 + rank, 1 << width)
        codes.append((code, width))
        rank = 0 if code == 256 else rank + 1
    return lzw_pack(codes)


def _libtiff_lzw_strips() -> list[tuple[bytes, int]]:
    """LZW strips libtiff wrote (through Pillow), with the bytes each holds."""
    try:
        from PIL import Image
    except ImportError:
        return []
    import io

    rng = np.random.default_rng(5)
    grid = (np.cumsum(rng.normal(0, 0.4, (40, 600)), axis=1) + 100).astype("<f4")
    buffer = io.BytesIO()
    Image.fromarray(grid).save(buffer, format="TIFF", compression="tiff_lzw")
    data = buffer.getvalue()
    (ifd,) = struct.unpack_from("<I", data, 4)
    (count,) = struct.unpack_from("<H", data, ifd)
    tags = {}
    for k in range(count):
        tag, kind, n, value = struct.unpack_from("<HHII", data, ifd + 2 + 12 * k)
        values = [value] if n == 1 else struct.unpack_from(f"<{n}{'I' if kind == 4 else 'H'}", data, value)
        tags[tag] = list(values)
    rows = tags[278][0]
    return [(data[o:o + n], min(rows, 40 - k * rows) * 600 * 4)
            for k, (o, n) in enumerate(zip(tags[273], tags[279], strict=True))]


def test_the_vectorised_lzw_decoder_matches_the_loop_decoder_on_random_libtiff_and_corrupt_streams():
    """The reader decodes LZW a Clear segment at a time, with pointer jumping
    and parallel writes; the browser and the spec use the loop. Every stopping
    rule - the block's end, a missing end code, the table's 5,119 entries, a
    code no table holds, data that runs out - has to fall at the same code in
    both, or the two engines read one strip two ways. Some thousands of
    cases: libtiff's own streams, the test encoder's with early and
    deferred Clears and without an end code, codes at random with Clears
    every few codes or hardly ever, and all of those cut short or with bits
    flipped."""
    rng = random.Random(41)

    def outcome(decode, data, expected):
        try:
            return decode(data, expected)
        except _CodecError as refused:
            return refused.code

    streams = [(strip, size) for strip, size in _libtiff_lzw_strips()]
    for _ in range(800):
        size = rng.choice([0, 1, 3, 40, 300, 1200, 2500])
        data = bytes(rng.choice(rng.choice([b"A", b"AB", b"0123456789", bytes(range(256))]))
                     for _ in range(size))
        form = rng.random()
        if form < 0.2:
            stream = lzw_encode(data)
        elif form < 0.3:
            stream = lzw_encode(data, limit=rng.randrange(258, 600))  # a Clear every few hundred codes
        elif form < 0.4:
            stream = lzw_encode(data, limit=4096, defer=rng.choice([0, 1, 1024, 1025, 3000]))
        elif form < 0.5:
            stream = lzw_encode(data, end=False)
        else:
            stream = _random_lzw_codes(rng, rng.choice([0.002, 0.03, 0.3]))
            size = rng.randrange(2000)
        streams.append((stream, size))
    cases = []
    for stream, size in streams:
        damaged = bytearray(stream)
        for _ in range(rng.randrange(1, 4)):
            if damaged:
                damaged[rng.randrange(len(damaged))] ^= 1 << rng.randrange(8)
        for data in (stream, bytes(damaged), stream[:rng.randrange(len(stream) + 1)]):
            cases += [(data, expected) for expected in {size, max(size - 1, 0), size + 1, rng.randrange(size + 2)}]
    assert len(cases) > 4000
    differ, verdicts = [], set()
    for data, expected in cases:
        reference = outcome(_lzw_decode_loop, data, expected)
        verdicts.add(reference if isinstance(reference, str) else "read")
        if outcome(_lzw_decode, data, expected) != reference:
            differ.append((len(data), expected))
    assert not differ, f"{len(differ)} of {len(cases)} streams decode differently, first {differ[:5]}"
    # and the cases reach every outcome, so agreement is not agreement on one verdict
    assert {"read", "damaged"} <= verdicts


def test_a_stream_that_clears_after_every_code_or_two_decodes_as_fast_as_the_loop():
    """Short segments are decoded many at a time. Taken one at a time, a
    stream that clears after every code or two - which no encoder writes,
    but a file can hold - took fifty times as long as the loop, enough for
    one crafted upload to hold the server for many minutes."""
    import time

    stream = lzw_pack([pair for k in range(20000) for pair in ((256, 9), (65 + k % 20, 9), (66, 9))])
    timings = {}
    for decode in (_lzw_decode_loop, _lzw_decode):
        start = time.perf_counter()
        assert decode(stream, 40000)[:6] == b"ABBBCB"
        timings[decode] = time.perf_counter() - start
    assert timings[_lzw_decode] < 4 * timings[_lzw_decode_loop] + 0.05


# ------------------------------------------------------------------ reader
#
# The raw reader of PLAN.md step 4.1. The committed fixtures are written by
# tests/webapp/fixtures/make_dem_fixture.py, tests/test_dem_fixtures.py holds
# them to GDAL, and their MANIFEST.json says what each must read as. A file a
# test needs that is not committed is made here with the same builder.

DEM = Path(__file__).resolve().parent / "webapp" / "fixtures" / "dem"
MANIFEST = json.loads((DEM / "MANIFEST.json").read_text(encoding="ascii"))["files"]
READ = sorted(name for name, entry in MANIFEST.items() if entry["raw"] == "read")
DTYPES = {(1, 8): "u1", (2, 8): "i1", (1, 16): "u2", (2, 16): "i2",
          (1, 32): "u4", (2, 32): "i4", (3, 32): "f4", (3, 64): "f8"}
LAYOUT_FACTS = ("byte_order", "bigtiff", "width", "height", "tiled", "block_width", "block_height",
                "rows_per_strip", "compression", "predictor", "sample_format", "bits", "model_type",
                "raster_type", "epsg", "x0", "y0", "sx", "sy")
SX = 1 / 1200


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


def _file(rows=None, kind="f32", **options) -> tuple[bytes, bytes]:
    """A one-image GeoTIFF from the fixture builder, and the samples it holds
    as GDAL reads them (north row first, each little-endian)."""
    rows = MAKE.metres(MAKE.patch(9, 7, 61)) if rows is None else rows
    georef = options.pop("georef", MAKE.Georef(-11.9, 8.4, SX, SX, raster=1))
    made = MAKE.single("made.tif", "", rows, kind, georef, **options)
    return made.data, made.samples


def _refused(source, name: str = "made.tif") -> GeoTiffError:
    with pytest.raises(GeoTiffError) as refused:
        read_geotiff(source, name)
    return refused.value


def _north_first(raster, kind: str) -> bytes:
    """The reader's samples, north row first, little-endian in the file's own type."""
    return raster.z[::-1].astype(np.dtype(kind).newbyteorder("<")).tobytes()


def _gdal_view(raster, entry: dict) -> bytes:
    """The reader's samples put back as GDAL reads the file, so as to compare
    like with like: a sparse block is 0 to GDAL and a void to the reader, a
    no-data cell holds the no-data value, and a stored -0 is still -0."""
    layout = raster.layout
    z = raster.z[::-1].copy()
    sparse = _sparse_cells(layout, entry.get("sparse_blocks", []))
    if layout.nodata is not None:
        z[np.isnan(z) & ~sparse] = layout.nodata
    z[sparse] = 0
    for row, col in entry.get("negative_zero_cells", []):
        z[row, col] = -0.0
    return z.astype(np.dtype(DTYPES[layout.sample_format, layout.bits]).newbyteorder("<")).tobytes()


def _sparse_cells(layout, blocks) -> np.ndarray:
    sparse = np.zeros((layout.height, layout.width), dtype=bool)
    for index in blocks:
        row0, col0, rows, cols, _, _ = _block_geometry(layout, index)
        sparse[row0:row0 + rows, col0:col0 + cols] = True
    return sparse


@pytest.mark.parametrize("name", sorted(MANIFEST))
def test_every_committed_fixture_is_read_or_refused_as_its_manifest_says(name):
    """The raw reader's verdict on each fixture, a refusal by its catalogue
    id, and the layout the manifest states, the first cell centres to the
    bit. The browser's reader is held to the same files through parity; a
    Python reader that drifted from the manifest would take the parity
    reference with it."""
    entry = MANIFEST[name]
    if entry["raw"] != "read":
        refusal = _refused(DEM / name, name)
        assert refusal.ident == entry["raw"]
        assert str(refusal) == phrase(entry["raw"], **refusal.values)
        return
    layout = read_geotiff(DEM / name).layout
    for key in LAYOUT_FACTS:
        if key in entry:
            assert getattr(layout, key) == entry[key], key
    assert (layout.name, layout.size) == (name, (DEM / name).stat().st_size)
    assert layout.ifd_index == entry.get("ifd_index", 0)
    assert layout.predictor_applied is (layout.predictor != 1 and layout.compression in (5, 8, 32946))
    assert layout.has_nodata_tag is ("nodata" in entry)
    want = entry.get("nodata_value")
    if want in (None, "no cell"):
        assert layout.nodata is None
    elif want == "nan":
        assert layout.nodata is not None and math.isnan(layout.nodata)
    elif want in ("inf", "-inf"):
        assert layout.nodata == float(want)
    else:
        assert layout.nodata == want and type(layout.nodata) is type(want)


@pytest.mark.parametrize("name", READ)
def test_every_committed_fixture_holds_the_samples_gdal_reads_in_it(name):
    """Every sample, put back as GDAL reads it, hashes to the manifest's
    digest of GDAL's own read. Without rasterio this is still a check
    against GDAL, made when the fixtures were: a plane read in the wrong
    byte order or a code widened late cannot pass it."""
    raster = read_geotiff(DEM / name)
    assert hashlib.sha256(_gdal_view(raster, MANIFEST[name])).hexdigest() == MANIFEST[name]["samples_sha256"]


@pytest.mark.parametrize("name", READ)
def test_each_void_is_given_the_reason_the_manifest_counts(name):
    """Within the elevation layer's bounds (-1000 to 9000 m) the reasons of
    every block add up to the manifest's no-data and implausible counts. The
    raw layer, given no bounds, voids only no data: an infinity or a fill
    value is the elevation layer's to judge, not the file format's."""
    data = (DEM / name).read_bytes()
    layout = open_geotiff(name, len(data), lambda offset, length: data[offset:offset + length])
    found = {1: 0, 2: 0}
    for index, offset, length, rows in block_ranges(layout, 0, layout.height, 0, layout.width):
        block = data[offset:offset + length]
        values, reasons = decode_block(layout, index, block, rows, bounds=(-1000.0, 9000.0))
        raw_values, raw_reasons = decode_block(layout, index, block, rows)
        for reason in found:
            found[reason] += int((reasons == reason).sum())
        assert np.array_equal(raw_reasons == 1, reasons == 1) and not (raw_reasons == 2).any()
        assert np.array_equal(np.isnan(values), reasons != 0)
        assert np.array_equal(np.isnan(raw_values), raw_reasons != 0)
    voids = MANIFEST[name].get("voids", {"no_data": 0, "implausible": 0})
    assert (found[1], found[2]) == (voids["no_data"], voids["implausible"])


def _gdal_open(rasterio, name: str):
    index = MANIFEST[name].get("ifd_index", 0)
    path = str(DEM / name)
    return rasterio.open(f"GTIFF_DIR:{index + 1}:{path}" if index else path)


def _assert_reads_as_gdal(raster, band, transform, sparse_blocks=()) -> None:
    """Every value the reader keeps is GDAL's to the bit (once -0 is read as
    +0), every void is no data to GDAL too (NaN, the no-data value, or a
    sparse block GDAL reads as 0), and every centre is GDAL's within 1e-12
    degree or 1e-9 m: not to the bit, because GDAL computes
    (X - 0.5*Sx) + (i + 0.5)*Sx where both engines compute x0 + i*Sx."""
    layout = raster.layout
    z = raster.z[::-1]
    assert z.shape == band.shape
    kept = ~np.isnan(z)
    assert np.array_equal(z[kept].view(np.uint64), (band[kept] + 0.0).view(np.uint64))
    gdal_void = np.isnan(band) | _sparse_cells(layout, sparse_blocks)
    if layout.nodata is not None:
        gdal_void |= band == layout.nodata
    assert np.array_equal(~kept, gdal_void)
    tolerance = 1e-9 if layout.model_type == 1 else 1e-12
    across, down = np.arange(layout.width), np.arange(layout.height - 1, -1, -1)
    assert np.abs(transform.c + (across + 0.5) * transform.a - raster.x).max() <= tolerance
    assert np.abs(transform.f + (down + 0.5) * transform.e - raster.y).max() <= tolerance


@pytest.mark.parametrize("name", READ)
def test_every_committed_fixture_reads_as_gdal_reads_it(name, rasterio):
    """GDAL itself, through rasterio, on each file the reader reads: values
    bit for bit, voids where GDAL has no data, centres within 1e-12 degree.
    The trap a reuser must know: a sparse block is 0 to GDAL when the file
    has no no-data value; the reader voids it."""
    raster = read_geotiff(DEM / name)
    with _gdal_open(rasterio, name) as dataset:
        band = dataset.read(1, masked=False).astype(np.float64)
        transform = dataset.transform
    _assert_reads_as_gdal(raster, band, transform, MANIFEST[name].get("sparse_blocks", ()))


def test_the_reader_agrees_with_gdal_on_files_gdal_wrote(tmp_path, rasterio):
    """The matrix of spec section 7.1, written by GDAL here rather than by
    this project's builder: LZW and DEFLATE with each predictor, and no
    compression and PackBits without one, in int16, float32 and float64,
    tiled and striped, little- and big-endian, PixelIsArea and
    PixelIsPoint, in degrees and in UTM metres. An encoder and a decoder
    that share a misunderstanding agree with each other; they cannot both
    agree with GDAL."""
    from rasterio.transform import Affine

    height, width = 21, 37
    r, c = np.mgrid[0:height, 0:width]
    surfaces = {
        "int16": ((r * 37 + c * 11) % 3000 - 500).astype(np.int16),
        "float32": (r * 0.37 - c * 1.3 + (r * c % 7) / 8).astype(np.float32),
        "float64": r * 0.37 - c * 1.3 + (r * c % 7) / 3,
    }
    for grid in surfaces.values():
        grid[2, 3] = grid[17, 30] = -9999
    places = {4326: (-12.0, 9.0, 1 / 1200), 32629: (700000.0, 950000.0, 30.0)}
    methods = {"LZW": 5, "DEFLATE": 8, "NONE": 1, "PACKBITS": 32773}
    encodings = [(m, p) for m in ("LZW", "DEFLATE") for p in (1, 2, 3)] + [("NONE", 1), ("PACKBITS", 1)]
    failures, written = [], 0
    for (method, predictor), dtype, tiled, endian, point, epsg in itertools.product(
            encodings, surfaces, (True, False), ("LITTLE", "BIG"), (False, True), places):
        if predictor == 3 and dtype == "int16":
            continue  # the floating-point predictor is for floats, and GDAL will not write it on integers
        west, north, step = places[epsg]
        shape, kind = "tiled" if tiled else "strips", "point" if point else "area"
        path = tmp_path / f"{method}_p{predictor}_{dtype}_{shape}_{endian}_{kind}_{epsg}.tif"
        blocks = {"tiled": True, "blockxsize": 16, "blockysize": 16} if tiled else {"blockysize": 5}
        with rasterio.open(path, "w", driver="GTiff", width=width, height=height, count=1, dtype=dtype,
                           crs=f"EPSG:{epsg}", transform=Affine(step, 0.0, west, 0.0, -step, north),
                           nodata=-9999, compress=method, predictor=predictor, endianness=endian,
                           **blocks) as sink:
            sink.update_tags(AREA_OR_POINT="Point" if point else "Area")
            sink.write(surfaces[dtype], 1)
        written += 1
        raster = read_geotiff(path)
        with rasterio.open(path) as dataset:
            band = dataset.read(1, masked=False).astype(np.float64)
            transform = dataset.transform
        layout = raster.layout
        facts = (layout.compression, layout.predictor, layout.tiled, layout.byte_order, layout.raster_type,
                 layout.epsg, layout.model_type)
        if facts != (methods[method], predictor, tiled, ">" if endian == "BIG" else "<", 2 if point else 1,
                     epsg, 2 if epsg == 4326 else 1):
            failures.append(f"{path.name}: {facts}")
            continue
        try:
            _assert_reads_as_gdal(raster, band, transform)
        except AssertionError:
            failures.append(path.name)
    assert written == 352
    assert not failures, failures


def test_the_reader_returns_what_the_writer_wrote_cell_for_cell(tmp_path):
    """The PR #54 writer's output - UTM, PixelIsArea, float32, NaN as no
    data - read back through the raw layer: every cell, the right way up,
    each centre half a cell in from the corner the writer was given, and
    the coordinate system it wrote. The writer is anchored to GDAL already;
    this anchors the reader to the writer."""
    grid = np.arange(7 * 5, dtype=float).reshape(7, 5) * 1.25 - 3.0
    grid[0, 0] = np.nan
    grid[6, 4] = 1e-3
    path = write_geotiff(tmp_path / "grid.tif", grid, west=700000.0, north=950600.0, pixel_width=100.0,
                         pixel_height=50.0, epsg=utm_epsg(29))
    raster = read_geotiff(path)
    assert np.array_equal(raster.z, grid.astype(np.float32).astype(float), equal_nan=True)
    layout = raster.layout
    assert (layout.model_type, layout.epsg, layout.raster_type) == (1, 32629, 1)
    assert (layout.sample_format, layout.bits, layout.compression) == (3, 32, 1)
    assert layout.nodata is not None and math.isnan(layout.nodata)
    assert raster.x.tolist() == [700050.0 + i * 100.0 for i in range(5)]
    assert raster.y.tolist() == [950575.0 - (6 - r) * 50.0 for r in range(7)]


def test_a_pixel_is_point_tile_is_centred_on_its_tie_point_and_a_pixel_is_area_file_half_a_cell_in():
    """A Copernicus tile ties its first cell's centre to whole degrees
    (PixelIsPoint); a GDAL default file ties its first cell's corner
    (PixelIsArea), with no raster type key meaning the same. Read the one
    as the other and every cell moves half a cell - about 15 m - and still
    opens happily."""
    point = read_geotiff(DEM / "Copernicus_DSM_COG_10_N08_00_W011_00_DEM.tif")
    assert (point.layout.raster_type, point.layout.x0, point.layout.y0) == (2, -11.0, 9.0)
    sx = 1 / 3600
    for raster_type, x0, y0 in ((2, -11.0, 9.0), (1, -11.0 + 0.5 * sx, 9.0 - 0.5 * sx),
                                (None, -11.0 + 0.5 * sx, 9.0 - 0.5 * sx)):
        data, _ = _file(georef=MAKE.Georef(-11.0, 9.0, sx, sx, raster=raster_type))
        layout = read_geotiff(data).layout
        assert (layout.x0, layout.y0) == (x0, y0), raster_type
    # a tiepoint at raster point (3, 2) rather than the corner
    area = read_geotiff(DEM / "le_lzw_p3_f64.tif").layout
    assert area.x0 == ((-11.7 + 3 * SX) - 3.0 * SX) + 0.5 * SX
    assert area.y0 == ((7.9 - 2 * SX) + 2.0 * SX) - 0.5 * SX
    # and the cell centres are the first one plus a whole number of cells, never np.arange's steps
    raster = read_geotiff(DEM / "le_lzw_p3_f64.tif")
    assert raster.x.tolist() == [area.x0 + i * area.sx for i in range(area.width)]


@pytest.mark.parametrize("name", ["pred2_none.tif", "pred2_packbits.tif"])
def test_a_predictor_tag_is_ignored_without_lzw_or_deflate_as_gdal_does(name):
    """libtiff sets a predictor up only inside its LZW and Deflate codecs, so
    with no compression or PackBits GDAL reads the stored values whatever
    the tag says. A reader that undid it there would scramble heights GDAL
    reads correctly; one that refused it would refuse a file GDAL opens."""
    raster = read_geotiff(DEM / name)
    assert (raster.layout.predictor, raster.layout.predictor_applied) == (2, False)
    assert hashlib.sha256(_gdal_view(raster, MANIFEST[name])).hexdigest() == MANIFEST[name]["samples_sha256"]
    # even the floating-point predictor on integers, which LZW would refuse
    rows = MAKE.whole_metres(MAKE.patch(9, 7, 62))
    data, samples = _file(rows, "i16", predictor=3, rows_per_strip=3)
    assert _north_first(read_geotiff(data), "i2") == samples
    data, _ = _file(rows, "i16", predictor=3, compression=5, rows_per_strip=3)
    refusal = _refused(data)
    assert (refusal.ident, refusal.values["code"]) == ("terrain.predictor", 3)


def test_floating_point_predictor_planes_are_most_significant_byte_first_in_both_byte_orders():
    """libtiff's floating-point predictor splits each row into byte planes,
    most significant first whatever the file's byte order, and differences
    straight through them. A reader that swaps a big-endian file's bytes
    after the predictor, as Pillow 12.3 does, or takes a little-endian
    file's planes least significant first, reads every height as some other
    number."""
    rows = [[(r * 7 + c * 13) * 0.731 - 40 for c in range(19)] for r in range(9)]
    for kind, order, compression in itertools.product(("f32", "f64"), ("<", ">"), (5, 8, 32946)):
        data, samples = _file(rows, kind, order=order, compression=compression, predictor=3, rows_per_strip=4)
        assert _north_first(read_geotiff(data), "f" + kind[1:].replace("32", "4").replace("64", "8")) == samples
    data, samples = _file(rows, "f32", compression=8, predictor=3, rows_per_strip=9)
    layout = read_geotiff(data).layout
    planes = np.cumsum(np.frombuffer(zlib.decompress(data[layout.offsets[0]:]), dtype=np.uint8).reshape(9, 76),
                       axis=1, dtype=np.uint8).reshape(9, 4, 19).transpose(0, 2, 1)
    assert np.ascontiguousarray(planes).view(">f4").astype("<f4").tobytes() == samples
    assert np.ascontiguousarray(planes).view("<f4").tobytes() != samples


def test_horizontal_predictor_on_float32_and_float64_words_adds_the_bit_patterns():
    """FABDEM's tiles carry predictor 2 on float32 samples: each word is the
    difference of the bit patterns, as unsigned integers in the file's byte
    order, wrapping. Adding the floats instead, or the words in the host's
    order, gives other numbers that look like heights."""
    rows = [[1.5, -2.25, 3.0e38, 1e-30, 7.0, -0.125], [250.0, 250.5, -250.0, 0.0, 1e10, 2.0]]
    for kind, order, compression in itertools.product(("f32", "f64"), ("<", ">"), (5, 8)):
        data, samples = _file(rows, kind, order=order, compression=compression, predictor=2, rows_per_strip=1)
        assert _north_first(read_geotiff(data), "f" + str(int(kind[1:]) // 8)) == samples
    # one row by hand: each word less the one before, modulo 2**32, big-endian
    words = np.array([1.5, -2.25, 7.0], dtype=">f4").view(">u4").astype(np.int64)
    differences = np.array([words[0], *np.diff(words)]) % (1 << 32)
    data, _ = _file([[0.0, 0.0, 0.0]], "f32", order=">", compression=8, predictor=2)
    layout = read_geotiff(data).layout
    values, _ = decode_block(layout, 0, zlib.compress(differences.astype(">u4").tobytes()))
    assert values.tolist() == [[1.5, -2.25, 7.0]]


def _pillow_geotags(predictor: int):
    from PIL import TiffImagePlugin

    tags = TiffImagePlugin.ImageFileDirectory_v2()
    for tag, kind, value in ((33550, 12, (SX, SX, 0.0)), (33922, 12, (0.0, 0.0, 0.0, -12.0, 9.0, 0.0)),
                             (34735, 3, (1, 1, 0, 3, 1024, 0, 1, 2, 1025, 0, 1, 1, 2048, 0, 1, 4326))):
        tags[tag] = value
        tags.tagtype[tag] = kind
    if predictor != 1:
        tags[317] = predictor
        tags.tagtype[317] = 3
    return tags


def test_lzw_strips_written_by_pillows_libtiff_read_back_byte_for_byte():
    """libtiff's own LZW encoder, through Pillow, with each predictor: an
    encoder this project did not write. Little-endian only: Pillow is an
    oracle only where it is right, and Pillow 12.3 reads a big-endian
    floating-point-predictor file wrongly - GDAL's own big-endian fixture
    comes out near 1e-41 - because it swaps the bytes of planes that are
    most significant first whatever the file's byte order."""
    Image = pytest.importorskip("PIL.Image")
    import io

    rng = np.random.default_rng(7)
    heights = (np.cumsum(rng.normal(0, 0.5, (170, 300)), axis=1) + 250).astype("<f4")
    counts = (np.cumsum(rng.integers(0, 9, (170, 300)), axis=1) % 65536).astype("<u2")
    for grid, predictors in ((heights, (1, 2, 3)), (counts, (1, 2))):
        for predictor in predictors:
            buffer = io.BytesIO()
            Image.fromarray(grid).save(buffer, format="TIFF", compression="tiff_lzw",
                                       tiffinfo=_pillow_geotags(predictor))
            raster = read_geotiff(buffer.getvalue(), "pillow.tif")
            layout = raster.layout
            assert (layout.compression, layout.predictor, layout.byte_order) == (5, predictor, "<")
            assert len(layout.offsets) > 1, "one strip would not test where strips meet"
            assert np.array_equal(raster.z[::-1], grid), (grid.dtype, predictor)


def test_every_codec_failure_reads_as_the_same_damaged_block_sentence():
    """A broken DEFLATE stream, a broken LZW stream, short PackBits and a
    short uncompressed block all read as one sentence naming the block (from
    1) and the bytes it should hold. Matching each library's own words
    would make the browser's reader, with its own inflate, disagree with
    this one about nothing that matters to the operator."""
    rows = MAKE.metres(MAKE.patch(11, 9, 63))
    for compression in (1, 5, 8, 32946, 32773):
        data, _ = _file(rows, compression=compression, rows_per_strip=4)
        layout = read_geotiff(data, "broken.tif").layout
        offset, count = layout.offsets[1], layout.byte_counts[1]
        block = data[offset:offset + count]
        flipped = bytearray(block)
        flipped[len(block) // 2] ^= 0x55
        for broken in (block[:count // 2], b"", bytes(flipped) if compression != 1 else block[:-1]):
            if compression == 32773 and broken == bytes(flipped):
                continue  # a flipped PackBits byte can still decode; it is just wrong
            with pytest.raises(GeoTiffError) as refused:
                decode_block(layout, 1, broken)
            expected = 4 * 11 * 4
            assert refused.value.ident == "terrain.block_damaged"
            assert refused.value.code == "block_damaged"
            assert refused.value.values == {"n": 2, "file": "broken.tif", "bytes": expected}
            assert str(refused.value) == (f"Data block 2 of broken.tif is damaged: it does not decompress to "
                                          f"the {expected} bytes the file says it holds, so download the file again.")
    # and in a whole file, the committed stream with a bad Adler-32
    assert _refused(DEM / "refuse_bad_adler.tif").values["n"] == 1


@pytest.mark.parametrize("tag, tiled", [(256, False), (257, False), (322, True), (323, True), (278, False)])
def test_zero_image_tile_or_strip_sizes_are_refused_rather_than_divided_by(tag, tiled):
    """A zero width, height, tile size or RowsPerStrip is a damaged entry,
    caught before the block table divides by it, and the sentence names the
    tag. Every block count is computed from these, so a reader that divided
    first would fail with an arithmetic error instead of a sentence."""
    data, _ = _file(tile=(16, 16) if tiled else None, rows_per_strip=None if tiled else 3,
                    tags={tag: (MAKE.SHORT, [0])})
    refusal = _refused(data)
    names = {256: "ImageWidth", 257: "ImageLength", 322: "TileWidth", 323: "TileLength", 278: "RowsPerStrip"}
    assert (refusal.ident, refusal.values["tag"]) == ("terrain.bad_tag", names[tag])


def test_bigtiff_reads_eight_byte_offsets_and_counts():
    """FABDEM and large GDAL outputs are BigTIFF: a 16-byte header, 20-byte
    entries and eight-byte offsets and counts. Offsets of 2**53 and more are
    refused, because the browser reads a 64-bit word as two 32-bit halves
    and keeps it exact only below that."""
    for name in ("bigtiff_deflate_p2_f32.tif", "bigtiff_be_lzw_p2_i32.tif"):
        raster = read_geotiff(DEM / name)
        assert raster.layout.bigtiff
        assert hashlib.sha256(_gdal_view(raster, MANIFEST[name])).hexdigest() == MANIFEST[name]["samples_sha256"]
    rows = MAKE.metres(MAKE.patch(10, 8, 64))
    data, samples = _file(rows, bigtiff=True, rows_per_strip=3, order=">")
    assert _north_first(read_geotiff(data), "f4") == samples
    # the first directory's offset at the limit, and one short of it
    order = ">"
    for offset, ident in ((1 << 53, "terrain.too_large"), ((1 << 53) - 1, "terrain.ends_early")):
        assert _refused(data[:8] + struct.pack(order + "Q", offset) + data[16:]).ident == ident
    assert _refused(data[:4] + struct.pack(order + "H", 4) + data[6:]).ident == "terrain.not_tiff"


def test_overviews_and_masks_are_skipped_for_the_first_full_resolution_image():
    """COGs and pyramids keep reduced-resolution images and masks beside the
    image, before it as often as after. The reader takes the first
    directory that is neither, walks at most 64, and says so when there is
    none or the chain loops back on itself rather than walking it for ever."""
    raster = read_geotiff(DEM / "overview_mask_first.tif")
    assert raster.layout.ifd_index == 2
    entry = MANIFEST["overview_mask_first.tif"]
    assert hashlib.sha256(_gdal_view(raster, entry)).hexdigest() == entry["samples_sha256"]
    assert _refused(DEM / "refuse_overview_only.tif").ident == "terrain.no_full_image"
    assert _refused(DEM / "refuse_ifd_loop.tif").ident == "terrain.directory_loop"
    georef = MAKE.Georef(-11.9, 8.4, SX, SX, raster=1)

    def chain(overviews: int) -> bytes:
        directories = []
        for _ in range(overviews):
            overview = MAKE.image([[1.0]], "f32", "<")
            overview.tags[MAKE.NEW_SUBFILE_TYPE] = (MAKE.LONG, [1])
            directories.append(overview)
        full = MAKE.image([[5.0, 6.0]], "f32", "<")
        full.tags.update(georef.tags())
        return MAKE.assemble("<", [*directories, full])

    assert read_geotiff(chain(63)).layout.ifd_index == 63
    assert read_geotiff(chain(63)).z.tolist() == [[5.0, 6.0]]
    assert _refused(chain(64)).ident == "terrain.no_full_image"


def test_gdal_block_leaders_and_trailers_are_never_read_as_data():
    """GDAL's COGs put each block's size before it and repeat its last four
    bytes after it, outside the byte count. A reader that took either as
    data would hand the decoder four bytes of junk before its stream or
    after it, so overwriting every one of them must change nothing."""
    ghosted = ["Copernicus_DSM_COG_10_N08_00_W012_00_DEM.tif", "gdal_cog_deflate_p3_f32.tif"]
    for name in ghosted:
        data = bytearray((DEM / name).read_bytes())
        original = read_geotiff(bytes(data), name)
        layout = original.layout
        for offset, count in zip(layout.offsets, layout.byte_counts, strict=True):
            assert data[offset - 4:offset] == struct.pack("<I", count)
            data[offset - 4:offset] = b"\xff" * 4
            data[offset + count:offset + count + 4] = b"\xff" * 4
        assert np.array_equal(read_geotiff(bytes(data), name).z, original.z, equal_nan=True)


def test_a_sparse_block_is_a_void_not_ground_at_zero():
    """A block with offset and byte count 0 holds no data. GDAL reads it as
    0 when the file has no no-data value, and a 0 m patch in an elevation
    model is sea; the reader voids it, with no-data as its reason, and asks
    for no bytes to do so."""
    data = (DEM / "sparse_f32.tif").read_bytes()
    raster = read_geotiff(data, "sparse_f32.tif")
    layout = raster.layout
    sparse = _sparse_cells(layout, MANIFEST["sparse_f32.tif"]["sparse_blocks"])
    z = raster.z[::-1]
    assert np.isnan(z[sparse]).all() and not np.isnan(z[~sparse]).any()
    ranges = {index: (offset, length) for index, offset, length, _ in block_ranges(layout, 0, 24, 0, 40)}
    for index in MANIFEST["sparse_f32.tif"]["sparse_blocks"]:
        assert ranges[index] == (0, 0)
        values, reasons = decode_block(layout, index, b"")
        assert values.shape == _block_geometry(layout, index)[2:4]  # an edge tile cropped to the image
        assert np.isnan(values).all() and (reasons == 1).all()


def test_negative_zero_samples_read_as_positive_zero():
    """-0 and +0 are equal, but numpy's maximum and the browser's
    Priority-Flood choose between them differently, so a stored -0 would set
    the two engines' filled surfaces apart in the sign of their zeros. Every
    sample is canonicalised with + 0.0 as it is decoded."""
    raster = read_geotiff(DEM / "negzero_f32.tif")
    z = raster.z[::-1]
    for row, col in MANIFEST["negzero_f32.tif"]["negative_zero_cells"]:
        assert z[row, col] == 0.0 and not np.signbit(z[row, col])
    assert not np.signbit(z[z == 0]).any()
    data, samples = _file([[-0.0, 1.0], [2.0, -0.0]], "f64", order=">")
    assert np.signbit(np.frombuffer(samples, "<f8")).sum() == 2
    assert not np.signbit(read_geotiff(data).z).any()


def test_nodata_strings_nan_inf_and_the_arcgis_float_form_match_gdal():
    """GDAL_NODATA is text, written several ways: 'nan', '-inf', ArcGIS's
    '-3.40282346639e+038' (a hair beyond float32, which GDAL clamps), with a
    trailing space or NUL, or empty. Each is read as GDAL reads it (the
    committed files' values are GDAL's, checked in test_dem_fixtures), and
    one that is not a number is refused with the text quoted."""
    flt_max = 3.4028234663852886e38
    nan = _parse_number(" NaN\x00")[0]
    assert nan is not None and math.isnan(nan)
    for text, sample_format, bits, value in [
        ("-9999", 3, 32, -9999.0), ("-32767", 2, 16, -32767), ("65535 ", 1, 16, 65535),
        ("\x00 +Inf\n", 3, 64, math.inf), ("-infinity", 3, 32, -math.inf),
        ("-3.40282346639e+038", 3, 32, -flt_max), ("3.5e38", 3, 32, flt_max), ("1e400", 3, 64, math.inf),
        ("0.1", 3, 32, float(np.float32(0.1))), ("0.1", 3, 64, 0.1), ("-0", 2, 16, 0), (".5e1", 2, 8, 5),
        ("1.5", 2, 16, None), ("70000", 1, 16, None), ("-1", 1, 8, None), ("nan", 2, 32, None),
        ("-inf", 1, 32, None), ("4294967295", 1, 32, 4294967295),
    ]:
        parsed, readable = _parse_number(text)
        assert readable and parsed is not None, text
        assert _cast_nodata(parsed, sample_format, bits) == value, text
    assert _parse_number(" \x00") == (None, True)
    for text in ("abc", "1,5", "0x10", "1e", "--1", "1 2", "nan5", "١"):
        assert _parse_number(text) == (None, False), text
    refusal = _refused(DEM / "nodata_abc.tif", "nodata_abc.tif")
    assert str(refusal) == "nodata_abc.tif gives its no-data value as abc, which is not a number."
    arcgis = read_geotiff(DEM / "nodata_arcgis_float_max.tif")
    assert arcgis.layout.nodata == -flt_max and np.isnan(arcgis.z[:, :2]).all()
    assert read_geotiff(DEM / "nodata_empty.tif").layout.nodata is None


def test_scaled_values_are_refused_rather_than_misread():
    """A GDAL scale or offset turns stored integers into metres. Applying it
    is GDAL's business and not this reader's, and reading the stored value
    as metres would put every hill ten times too high; so a scale other than
    1, or an offset other than 0, or one that is not a number, is refused."""
    assert _refused(DEM / "refuse_scaled.tif").ident == "terrain.scaled"
    read_geotiff(DEM / "le_lzw_p3_f64.tif")  # a scale of 1 and an offset of 0 are no scaling at all
    for items, ident in [
        ((("OFFSET", "offset", "100"),), "terrain.scaled"),
        ((("SCALE", "scale", "0.5"), ("OFFSET", "offset", "0")), "terrain.scaled"),
        ((("SCALE", "scale", "abc"),), "terrain.scaled"),
        ((("SCALE", "scale", ""),), "terrain.scaled"),
        ((("SCALE", "scale", " 1.0 "), ("OFFSET", "offset", "-0")), None),
        ((("", "unittype", "metre"), ("STATS", "description", "7")), None),
    ]:
        data, _ = _file(metadata=MAKE.metadata_xml(*items))
        if ident is None:
            read_geotiff(data)
        else:
            assert _refused(data).ident == ident, items


def test_rotated_flipped_and_control_point_files_are_refused():
    """The toolkit reads north-up grids only and does not resample, so a
    sheared, rotated or flipped transformation, a negative or zero pixel
    size, and a grid placed by control points are each refused with what
    they are, not read into the wrong place."""
    assert _refused(DEM / "refuse_rotated.tif").ident == "terrain.rotated"
    assert _refused(DEM / "refuse_control_points.tif").ident == "terrain.control_points"
    assert _refused(DEM / "refuse_no_georeference.tif").ident == "terrain.no_georeference"
    drop = (MAKE.MODEL_PIXEL_SCALE, MAKE.MODEL_TIEPOINT)
    for matrix in ([SX, 0.0, 0.0, -12.0, 0.0, SX, 0.0, 7.0],  # south-up
                   [-SX, 0.0, 0.0, -12.0, 0.0, -SX, 0.0, 7.0],  # east-west flipped
                   [SX, 0.0, 0.0, -12.0, 1e-6, -SX, 0.0, 7.0]):  # rotated
        data, _ = _file(tags={MAKE.MODEL_TRANSFORMATION: (MAKE.DOUBLE, matrix + [0.0] * 7 + [1.0])}, drop=drop)
        assert _refused(data).ident == "terrain.rotated", matrix
    for scale in ([SX, -SX, 0.0], [0.0, SX, 0.0], [-SX, SX, 0.0]):
        data, _ = _file(tags={MAKE.MODEL_PIXEL_SCALE: (MAKE.DOUBLE, scale)})
        assert _refused(data).ident == "terrain.rotated", scale
    # a pixel scale with no tiepoint places nothing
    data, _ = _file(drop=(MAKE.MODEL_TIEPOINT,))
    assert _refused(data).ident == "terrain.no_georeference"
    # and a north-up transformation is read as a scale and tiepoint would be
    data, _ = _file(tags={MAKE.MODEL_TRANSFORMATION: (MAKE.DOUBLE, [SX, 0.0, 0.0, -12.0, 0.0, -SX, 0.0, 7.0]
                                                      + [0.0] * 7 + [1.0])}, drop=drop)
    layout = read_geotiff(data).layout
    assert (layout.x0, layout.y0, layout.sx, layout.sy) == (-12.0 + 0.5 * SX, 7.0 - 0.5 * SX, SX, SX)


@pytest.mark.parametrize("code, method", [
    (2, "CCITT RLE"), (3, "CCITT Group 3"), (4, "CCITT Group 4"), (6, "old-style JPEG"), (7, "JPEG"),
    (34887, "LERC"), (34925, "LZMA"), (50000, "Zstandard"), (50001, "WebP"), (50002, "JPEG XL"),
    (99, "TIFF method 99"),
])
def test_each_unsupported_compression_is_refused_by_name(code, method):
    """JPEG, LERC, Zstandard and the rest are what GDAL and QGIS offer next
    to DEFLATE; an operator told "compression 50000" does not know what to
    change. Each is named, and a code nobody names is given as a number."""
    data, _ = _file(tags={MAKE.COMPRESSION: (MAKE.SHORT, [code])})
    refusal = _refused(data)
    assert (refusal.ident, refusal.values["method"]) == ("terrain.compression", method)
    assert str(refusal).startswith(f"made.tif is compressed with {method}, which")


def test_samples_the_reader_does_not_take_are_named_by_size_and_kind():
    """The sentence says what the file holds - 16-bit floating point,
    complex numbers - so the operator knows what to convert it to. An
    absent SampleFormat is unsigned and an absent BitsPerSample is one bit,
    as the TIFF rules have them."""
    def kind(sample_format, bits=None):
        tags = {MAKE.SAMPLE_FORMAT: (MAKE.SHORT, [sample_format])}
        if bits is not None:
            tags[MAKE.BITS_PER_SAMPLE] = (MAKE.SHORT, [bits])
        return tags

    for tags, drop, words in [
        (kind(3, 16), (), "16-bit floating-point"),
        (kind(2, 64), (), "64-bit signed integer"),
        (kind(6), (), "32-bit SampleFormat 6"),
        ({}, (MAKE.BITS_PER_SAMPLE, MAKE.SAMPLE_FORMAT), "1-bit unsigned integer"),
    ]:
        data, _ = _file(tags=tags, drop=drop)
        assert f"stores {words} samples;" in str(_refused(data)), words
    assert _refused(DEM / "refuse_two_bands.tif").values["n"] == 2
    data, _ = _file(tags={MAKE.FILL_ORDER: (MAKE.SHORT, [3])})
    assert _refused(data).values == {"file": "made.tif", "tag": "FillOrder"}


#: A plain file for the settled-rule cases below: f32 strips, degrees, PixelIsArea
_PLAIN = {"kind": "f32", "width": 9, "height": 7, "seed": 67, "rows_per_strip": 3,
          "georef": {"x": -11.9, "y": 8.4, "sx": SX, "sy": SX, "raster": 1, "model": 2, "epsg": 4326}}


@pytest.mark.parametrize("change, outcome", [
    # a Predictor tag is not looked at without LZW or DEFLATE, whatever it says
    ({"tags": [[317, 3, [7]]]}, {"predictor": 7, "predictor_applied": False}),
    ({"compression": 5, "tags": [[317, 3, [7]]]}, ("terrain.predictor", {"code": 7})),
    # field types: unsigned integers as BYTE, SHORT, LONG or LONG8; reals as DOUBLE; GeoKeys as SHORT; text as ASCII
    ({"retype": [[256, 4]]}, {"width": 9}), ({"retype": [[256, 1]]}, {"width": 9}),
    ({"retype": [[256, 8]]}, ("terrain.bad_tag", {"tag": "ImageWidth"})),
    ({"retype": [[256, 18]]}, ("terrain.bad_tag", {"tag": "ImageWidth"})),
    ({"retype": [[33550, 11]]}, ("terrain.bad_tag", {"tag": "ModelPixelScale"})),
    ({"retype": [[34735, 4]]}, ("terrain.bad_tag", {"tag": "GeoKeyDirectory"})),
    ({"nodata": "-9999", "retype": [[42113, 7]]}, ("terrain.bad_tag", {"tag": "GDAL_NODATA"})),
    # counts: one for a single value, at least one per sample, any number (none included) for the rest
    ({"tags": [[259, 3, [1, 1]]]}, ("terrain.bad_tag", {"tag": "Compression"})),
    ({"tags": [[258, 3, [32, 8]]]}, {"bits": 32}),
    ({"tags": [[42113, 2, ""]]}, {"nodata": None, "has_nodata_tag": True}),
    ({"tags": [[34736, 12, []]]}, {"width": 9}),
    # the subfile tags: a type TIFF does not define is skipped; a known one must hold one value in its entry
    ({"tags": [[254, 13, "01000000"]]}, {"ifd_index": 0}),
    ({"tags": [[254, 4, [0, 0]]]}, ("terrain.bad_tag", {"tag": "NewSubfileType"})),
    ({"tags": [[254, 16, [0]]]}, ("terrain.bad_tag", {"tag": "NewSubfileType"})),
    ({"tags": [[254, 16, [0]]], "bigtiff": True}, {"ifd_index": 0}),
    # FillOrder other than 1 and 2, a GeoKey directory of another version, a raster type other than 2
    ({"tags": [[266, 3, [3]]]}, ("terrain.bad_tag", {"tag": "FillOrder"})),
    ({"tags": [[34735, 3, [2, 1, 0, 1, 1024, 0, 1, 2]]]}, ("terrain.bad_tag", {"tag": "GeoKeyDirectory"})),
    ({"tags": [[34735, 3, [1, 1, 0, 2, 1024, 0, 1, 2, 1025, 0, 1, 3]]]}, {"raster_type": 1}),
    # a scale of one value is damaged before the missing tiepoint is noticed
    ({"tags": [[33550, 12, [SX]]], "drop": [33922]}, ("terrain.bad_tag", {"tag": "ModelPixelScale"})),
    # SampleFormat and BitsPerSample are a pair: 1 and 108 are not 2 and 8
    ({"tags": [[258, 3, [108]], [339, 3, [1]]]}, ("terrain.sample_type", {"bits": 108, "kind": "unsigned integer"})),
    # a LONG8 value past 2^53 is refused before any check reads it, here the compression's
    ({"bigtiff": True, "tags": [[266, 16, [1 << 53]], [259, 3, [50000]]]}, ("terrain.too_large", {})),
    # a count no reader could hold, on a tag the reader does not read, is passed over
    ({"bigtiff": True, "recount": [[262, 1 << 53]]}, {"width": 9}),
    ({"bigtiff": True, "recount": [[33550, 1 << 53]]}, ("terrain.too_large", {})),
    # RowsPerStrip 2^32 - 1 is the whole image even under a height past it
    ({"bigtiff": True, "kind": "u8", "rows_per_strip": None,
      "tags": [[257, 16, [1 << 33]], [278, 4, [0xFFFFFFFF]]]}, ("terrain.block_too_large", {"mb": 9 * 8192.0})),
], ids=lambda value: json.dumps(value)[:60] if isinstance(value, dict) else None)
def test_each_rule_settled_with_the_browser_reader_holds(change, outcome):
    """The rules the two readers were settled to (see the comments at each in
    geotiff.py and gwt-core.js): a predictor tag left unexamined without LZW
    or DEFLATE; the field types and counts each tag may have; a subfile tag
    of an unknown type skipped; FillOrder, GeoKey version and raster type;
    the order of the scale's checks; the sample type matched as a pair; a
    LONG8 value refused before any check; a count passed over on a tag
    nobody reads; RowsPerStrip 2^32 - 1. Each is pinned here without a
    browser, so a change to one rule in this engine fails by name rather
    than only as a disagreement in the Node tests."""
    data = MAKE.described_file({**_PLAIN, **change})
    if isinstance(outcome, dict):
        layout = geotiff_layout("made.tif", len(data), [(0, data)])
        assert isinstance(layout, GeoTiffLayout), layout
        for key, value in outcome.items():
            assert getattr(layout, key) == value, key
        return
    ident, values = outcome
    with pytest.raises(GeoTiffError) as refused:
        geotiff_layout("made.tif", len(data), [(0, data)])
    assert (refused.value.ident, refused.value.values) == (ident, {"file": "made.tif", **values})


def test_part_of_an_uncompressed_strip_is_refused_where_the_whole_strip_would_be():
    """A file cut short inside its one uncompressed strip: a window whose
    rows all lie before the cut is refused as the whole read is, because the
    strip as the file describes it runs past the end. The browser's reader
    once checked only the rows it read, and so read a window of a file this
    one refused."""
    data = MAKE.described_file({**_PLAIN, "rows_per_strip": None})
    layout = geotiff_layout("cut.tif", len(data) - 10, [(0, data[:-10])])
    assert isinstance(layout, GeoTiffLayout) and len(layout.offsets) == 1
    with pytest.raises(GeoTiffError) as refused:
        block_ranges(layout, 0, 2, 0, 9)
    assert refused.value.values == {"file": "cut.tif", "part": "data block 1"}


def _recount(data: bytes, tag: int, change: int) -> bytes:
    """A little-endian classic file with one entry's value count changed, its values left where they are."""
    (ifd,) = struct.unpack_from("<I", data, 4)
    (count,) = struct.unpack_from("<H", data, ifd)
    for k in range(count):
        at = ifd + 2 + 12 * k
        if struct.unpack_from("<H", data, at)[0] == tag:
            (n,) = struct.unpack_from("<I", data, at + 4)
            return data[:at + 4] + struct.pack("<I", n + change) + data[at + 8:]
    raise AssertionError(f"no tag {tag}")


def test_a_block_table_or_block_the_reader_cannot_use_is_refused_by_its_tag():
    """A block table of the wrong length names its offsets tag, or its byte
    counts when only those are wrong; a block that would decode to more
    than 64 MiB is refused before any of it is read, with its size; a tag
    of the wrong type is a damaged entry."""
    data, _ = _file(rows_per_strip=3, tags={MAKE.ROWS_PER_STRIP: (MAKE.SHORT, [2])})
    assert _refused(data).values["tag"] == "StripOffsets"  # four strips by the tag, three in the file
    data, _ = _file(rows_per_strip=2)
    assert _refused(_recount(data, MAKE.STRIP_BYTE_COUNTS, -1)).values["tag"] == "StripByteCounts"
    assert _refused(_recount(data, MAKE.STRIP_OFFSETS, -1)).values["tag"] == "StripOffsets"
    data, _ = _file(MAKE.metres(MAKE.patch(40, 20, 66)), tile=(16, 16))
    assert _refused(_recount(data, MAKE.TILE_BYTE_COUNTS, -1)).values["tag"] == "TileByteCounts"
    data, _ = _file(tags={MAKE.IMAGE_WIDTH: (MAKE.LONG, [5000]), MAKE.IMAGE_LENGTH: (MAKE.LONG, [5000]),
                          MAKE.ROWS_PER_STRIP: (MAKE.LONG, [5000])})
    refusal = _refused(data)
    assert refusal.ident == "terrain.block_too_large" and "in blocks of 95 MB," in str(refusal)
    data, _ = _file(tags={MAKE.IMAGE_WIDTH: (MAKE.DOUBLE, [9.0])})
    assert _refused(data).values["tag"] == "ImageWidth"


def test_a_truncated_file_says_what_is_missing():
    """An interrupted download is the commonest broken file. The sentence
    says which part the file ends before - its header, a directory, a tag's
    values or a data block, counted from 1 - so the operator knows it is the
    download, not the reader, at fault."""
    def part(source) -> str:
        refusal = _refused(source)
        assert refusal.ident == "terrain.ends_early"
        return refusal.values["part"]

    assert part(DEM / "refuse_truncated.tif") == "image directory"
    assert part(DEM / "refuse_truncated_data.tif") == "data block 4"
    data, _ = _file(rows_per_strip=1)
    assert part(data[:10]) == "file header"
    (count,) = struct.unpack_from("<H", data, 8)
    assert part(data[:8 + 2 + 12 * count + 4]) == "values of StripOffsets"
    assert _refused(b"GIF89a" + bytes(20)).ident == "terrain.not_tiff"
    assert _refused(b"II" + struct.pack("<H", 44) + bytes(20)).ident == "terrain.not_tiff"


@pytest.mark.parametrize("name", sorted(MANIFEST))
def test_the_layout_asks_only_for_the_bytes_it_still_needs(name):
    """Fed from 16 bytes, the layout asks round by round for what it needs
    next, never for bytes it has, never for any block's data, and ends where
    the whole file ends: the same layout or the same refusal. That is what
    lets the browser read a 48 MB tile's layout with a handful of small
    slices, and the parity suite holds the first round's request."""
    data = (DEM / name).read_bytes()

    def outcome(found):  # by repr, in which a NaN no-data value equals itself
        return repr(found) if isinstance(found, GeoTiffLayout) else (found.ident, str(found))

    try:
        whole = outcome(geotiff_layout(name, len(data), [(0, data)]))
    except GeoTiffError as refusal:
        whole = outcome(refusal)
    chunks = [(0, data[:16])]
    asked: list[tuple[int, int]] = []
    for _ in range(12):
        try:
            found = geotiff_layout(name, len(data), chunks)
        except GeoTiffError as refusal:
            found = refusal
        if not isinstance(found, list):
            break
        assert found and found == sorted(set(found))
        for offset, length in found:
            assert not any(start <= offset and offset + length <= start + len(held) for start, held in chunks)
            asked.append((offset, length))
            chunks.append((offset, data[offset:offset + length]))
    else:
        pytest.fail("the layout kept asking")
    assert outcome(found) == whole
    if isinstance(found, GeoTiffLayout):
        for offset, length in asked:
            for start, count in zip(found.offsets, found.byte_counts, strict=True):
                assert offset + length <= start or start + count <= offset, (offset, length)
    # the first round, which parity holds for both engines: the directory count or the directory itself
    first = geotiff_layout(name, len(data), [(0, data[:16])])
    if data[:2] in (b"II", b"MM") and isinstance(first, list):
        order = "<" if data[:2] == b"II" else ">"
        if struct.unpack_from(order + "H", data, 2)[0] == 43:
            assert first == [(struct.unpack_from(order + "Q", data, 8)[0], 8)]
        else:
            (ifd,) = struct.unpack_from(order + "I", data, 4)
            if ifd + 2 > 16:
                assert first == [(ifd, 2)]
            else:
                assert first == [(ifd + 2, 12 * struct.unpack_from(order + "H", data, ifd)[0] + 4)]


def test_the_driver_reads_a_cloud_optimised_file_at_once_and_others_in_64_kib_rounds():
    """open_geotiff reads the first 64 KiB, which holds a COG's every
    directory, then each range still needed rounded up to 64 KiB, and gives
    up after 16 more rounds rather than reading a broken chain for ever."""
    def reader(data, log, short=False):
        def read_at(offset, length):
            log.append((offset, length))
            return data[:16] if short and offset == 0 else b"" if short else data[offset:offset + length]
        return read_at

    for name in sorted(MANIFEST):
        data, log = (DEM / name).read_bytes(), []
        with contextlib.suppress(GeoTiffError):
            open_geotiff(name, len(data), reader(data, log))
        assert log == [(0, len(data))], name
    data, _ = _file(MAKE.metres(MAKE.patch(200, 120, 65)), rows_per_strip=10, ifds_first=False)
    assert len(data) > 65536
    (ifd,) = struct.unpack_from("<I", data, 4)
    log = []
    layout = open_geotiff("late.tif", len(data), reader(data, log))
    assert layout.width == 200 and log == [(0, 65536), (ifd, min(65536, len(data) - ifd))]
    log = []
    with pytest.raises(GeoTiffError) as refused:
        open_geotiff("short.tif", len(data), reader(data, log, short=True))
    assert refused.value.values["part"] == "image directory" and len(log) == 17


def test_only_blocks_that_meet_the_window_are_decoded():
    """A window reads the blocks it meets and nothing else - for an
    uncompressed strip, only the rows it wants - and what it reads is
    exactly the whole file's slice. A 48 MB tile read whole for a 15 km
    window would take a phone's memory and the analysis cap with it."""
    def window(name, data, j0, j1, i0, i1):
        log = []

        def read_at(offset, length):
            log.append((offset, length))
            return data[offset:offset + length]

        layout = open_geotiff(name, len(data), read_at)
        log.clear()
        out = np.full((j1 - j0, i1 - i0), -1.0)
        ranges = block_ranges(layout, j0, j1, i0, i1)
        for index, offset, length, rows in ranges:
            values, _ = decode_block(layout, index, read_at(offset, length) if length else b"", rows)
            row0, col0 = _block_geometry(layout, index)[:2]
            row0 += rows[0] if rows else 0
            top, left = max(j0, row0), max(i0, col0)
            bottom, right = min(j1, row0 + values.shape[0]), min(i1, col0 + values.shape[1])
            out[top - j0:bottom - j0, left - i0:right - i0] = values[top - row0:bottom - row0,
                                                                     left - col0:right - col0]
        return layout, ranges, [entry for entry in log if entry[1]], out

    name = "Copernicus_DSM_COG_10_N08_00_W012_00_DEM.tif"
    data = (DEM / name).read_bytes()
    layout, ranges, log, out = window(name, data, 3, 10, 20, 34)
    assert [index for index, *_ in ranges] == [1, 2]
    assert log == [(layout.offsets[k], layout.byte_counts[k]) for k in (1, 2)]
    whole = read_geotiff(data, name).z[::-1]
    assert np.array_equal(out, whole[3:10, 20:34])
    # an uncompressed strip is read only for the rows wanted
    name = "transform_f32.tif"
    data = (DEM / name).read_bytes()
    layout, ranges, log, out = window(name, data, 3, 5, 2, 9)
    row = layout.width * 4
    assert ranges == [(0, layout.offsets[0] + 3 * row, 2 * row, (3, 5))] and log == [ranges[0][1:3]]
    assert np.array_equal(out, read_geotiff(data, name).z[::-1][3:5, 2:9])
    assert block_ranges(layout, 9, 20, 0, 13) == [] and block_ranges(layout, 0, 4, 13, 20) == []
    # and every readable fixture, through windows of every shape, reads as its whole
    rng = random.Random(4)
    for name in READ:
        data = (DEM / name).read_bytes()
        whole = read_geotiff(data, name).z[::-1]
        height, width = whole.shape
        for _ in range(6):
            j0, i0 = rng.randrange(height), rng.randrange(width)
            j1, i1 = rng.randrange(j0, height) + 1, rng.randrange(i0, width) + 1
            layout, ranges, log, out = window(name, data, j0, j1, i0, i1)
            assert np.array_equal(out, whole[j0:j1, i0:i1], equal_nan=True), (name, j0, j1, i0, i1)
            assert len(log) == len({index for index, *_ in ranges if layout.byte_counts[index]})

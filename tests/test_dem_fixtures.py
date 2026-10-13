"""The committed elevation-model fixtures (tests/webapp/fixtures/dem/), checked twice over.

The files are written by tests/webapp/fixtures/make_dem_fixture.py, so the
first check is that what is committed is what that script writes. The second
is that each file says what the script means it to: GDAL, through rasterio,
opens every file a reader must read and must find exactly the samples, the
coordinate system, the raster type, the no-data value and the cell centres
the script intended. An encoder and a decoder that share a misunderstanding
- the floating-point predictor's byte order, LZW's early change - agree with
each other and are both wrong; they cannot both agree with GDAL. The readers
of PLAN.md step 4.1 are then held to these files, and through parity to each
other.

GDAL does two things here that the toolkit's reader does differently or not
at all, and both are traps for anyone reusing these tests:

* A sparse block (offset 0, byte count 0) reads as 0 in GDAL when the file
  has no no-data value. The reader voids it instead: a block that holds no
  data is not ground at 0 m. MANIFEST.json's samples_sha256 is GDAL's view,
  and its voids count the reader's.
* A Predictor tag is applied only with LZW or DEFLATE; with no compression or
  PackBits, libtiff and GDAL ignore it and read the stored values, and the
  reader copies them (pred2_none.tif, pred2_packbits.tif).

Some structural facts the fixtures exist to exercise are not visible through
GDAL at all - that GDAL's block leaders and trailers lie outside each block's
byte count, that a directory sits at the end of the file, the BigTIFF header -
so a few lines of struct below read those bytes directly. They are kept here
rather than borrowed from the builder, so that a builder bug cannot vouch for
itself.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import struct
import sys
import zlib
from functools import cache
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "webapp" / "fixtures"
DEM = FIXTURES / "dem"
CATALOGUE = Path(__file__).resolve().parents[1] / "src" / "groundwater" / "data" / "text" / "terrain.yaml"


def _maker():
    spec = importlib.util.spec_from_file_location("make_dem_fixture", FIXTURES / "make_dem_fixture.py")
    module = importlib.util.module_from_spec(spec)
    # a dataclass looks its module up in sys.modules while the class is made
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MAKE = _maker()
MANIFEST = json.loads((DEM / "MANIFEST.json").read_text(encoding="ascii"))
FILES = MANIFEST["files"]
READ = sorted(name for name, entry in FILES.items() if entry["raw"] == "read")
DTYPES = {(1, 8): "u1", (2, 8): "i1", (1, 16): "u2", (2, 16): "i2",
          (1, 32): "u4", (2, 32): "i4", (3, 32): "f4", (3, 64): "f8"}


@pytest.fixture
def rasterio():
    return pytest.importorskip("rasterio")


@cache
def _built():
    return MAKE.build()


def _intended(name: str) -> bytes:
    """The samples the builder meant the file to hold, as GDAL reads them (little-endian)."""
    if name in _built():
        return _built()[name].samples
    spec = next(s for s in MAKE.gdal_specs() if s.name == name)
    return MAKE.gdal_entry(spec)[1]


# --- a struct-only look at the bytes ---------------------------------------------------------

_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 16: 8, 17: 8, 18: 8}
_CODE = {3: "H", 4: "I", 8: "h", 9: "i", 11: "f", 12: "d", 16: "Q", 17: "q", 18: "Q"}


def _dump(data: bytes) -> dict:
    """The header and every directory of a TIFF: where each lies, and {tag: (type, values)}."""
    order = {b"II": "<", b"MM": ">"}[data[:2]]
    version = struct.unpack_from(order + "H", data, 2)[0]
    big = version == 43
    word, count_code, entry_size, inline = ("Q", "Q", 20, 8) if big else ("I", "H", 12, 4)
    at = struct.unpack_from(order + word, data, 8 if big else 4)[0]
    found, seen = [], set()
    while at and at not in seen:
        seen.add(at)
        n = struct.unpack_from(order + count_code, data, at)[0]
        tags = {}
        for k in range(n):
            pos = at + (8 if big else 2) + entry_size * k
            tag, kind = struct.unpack_from(order + "HH", data, pos)
            count = struct.unpack_from(order + word, data, pos + 4)[0]
            size = _SIZE[kind] * count
            where = pos + 4 + (8 if big else 4)
            if size > inline:
                where = struct.unpack_from(order + word, data, where)[0]
            raw = data[where:where + size]
            tags[tag] = (kind, raw if kind in (1, 2, 7) else struct.unpack(f"{order}{count}{_CODE[kind]}", raw))
        end = at + (8 if big else 2) + entry_size * n
        found.append({"at": at, "end": end + (8 if big else 4), "tags": tags})
        at = struct.unpack_from(order + word, data, end)[0]
    return {"order": order, "version": version, "bigtiff": big, "directories": found,
            "loops": bool(at) and at in seen}


def _blocks(directory: dict) -> list[tuple[int, int]]:
    tags = directory["tags"]
    offsets, counts = (324, 325) if 324 in tags else (273, 279)
    return list(zip(tags[offsets][1], tags[counts][1], strict=True))


def _geokeys(tags: dict) -> dict:
    if 34735 not in tags:
        return {}
    directory = tags[34735][1]
    return {directory[k]: directory[k + 3] for k in range(4, 4 + 4 * directory[3], 4) if directory[k + 1] == 0}


def _lzw(data: bytes, expected: int, table_limit: int) -> bytes:
    """The decoding loop of spec section 2.6, with the table bound as a parameter."""
    pos, bits = 0, len(data) * 8

    def read(width):
        nonlocal pos
        value = 0
        for _ in range(width):
            value = (value << 1) | ((data[pos >> 3] >> (7 - (pos & 7))) & 1)
            pos += 1
        return value

    out, width, following, prev = bytearray(), 9, 258, None
    table = {i: bytes((i,)) for i in range(256)}

    def add(entry):
        nonlocal following, width
        if following == table_limit:
            raise ValueError("the LZW table is full")
        table[following] = entry
        following += 1
        if following + 1 >= 1 << width and width < 12:
            width += 1

    while len(out) < expected and bits - pos >= width:
        code = read(width)
        if code == 257:
            break
        if code == 256:
            following, width, prev = 258, 9, None
            continue
        if prev is None:
            entry = table[code]
        elif code < following:
            entry = table[code]
            add(prev + entry[:1])
        elif code == following:
            entry = prev + prev[:1]
            add(entry)
        else:
            raise ValueError("an LZW code beyond the table")
        out += entry
        prev = entry
    if len(out) < expected:
        raise ValueError("the LZW strip ends early")
    return bytes(out[:expected])


def _unpackbits(data: bytes, expected: int) -> bytes:
    out, i = bytearray(), 0
    while len(out) < expected:
        n = data[i] - 256 if data[i] > 127 else data[i]
        i += 1
        if n >= 0:
            out += data[i:i + n + 1]
            i += n + 1
        elif n != -128:
            out += bytes((data[i],)) * (1 - n)
            i += 1
    return bytes(out[:expected])


# --- the files are what the builder writes ---------------------------------------------------

def test_the_committed_dem_fixtures_are_what_the_builder_writes():
    """Every committed file is the builder's output, and MANIFEST.json describes exactly that set.

    LZW, PackBits and uncompressed files are compared byte for byte; DEFLATE
    files by their tags and what each block inflates to, because zlib and
    zlib-ng write different bytes at the same level. Without this a fixture
    edited by hand, or left behind by an older builder, would quietly stop
    meaning what the manifest says, and both engines would be held to it.
    """
    problems = MAKE.check(DEM)
    assert not problems, "run python tests/webapp/fixtures/make_dem_fixture.py:\n" + "\n".join(problems)


def test_the_committed_set_stays_small_and_holds_no_hgt_tile():
    """The fixtures are synthetic and small: no real tile, no .hgt (2.9 MB or more), about 140 KB in all.

    A real Copernicus or SRTM tile may not be committed, and a fixture that
    grows past what a test needs makes every clone pay for it.
    """
    files = list(DEM.iterdir())
    assert not [p.name for p in files if p.suffix.lower() == ".hgt"]
    assert sum(p.stat().st_size for p in files) < 160_000
    assert max(p.stat().st_size for p in files if p.suffix == ".tif") < 16_000


def test_every_refusal_the_manifest_expects_is_a_catalogued_sentence():
    """A fixture's expected refusal names a sentence the catalogue holds.

    Otherwise the reader's tests would be written against a refusal no engine
    can word. Skipped until terrain.yaml exists (PR 4.1a, configuration and
    text).
    """
    if not CATALOGUE.is_file():
        pytest.skip("src/groundwater/data/text/terrain.yaml is not written yet")
    yaml = pytest.importorskip("yaml")
    catalogue = yaml.safe_load(CATALOGUE.read_text(encoding="utf-8"))
    expected = {v for entry in FILES.values() for v in (entry["raw"], entry["elevation"]) if v not in ("read", None)}
    assert expected <= {f"terrain.{key}" for key in catalogue}


# --- structure GDAL does not show --------------------------------------------------------------

def _ghosted() -> list[str]:
    names = []
    for name in sorted(FILES):
        data = (DEM / name).read_bytes()
        start = 16 if data[2:4] in (b"+\x00", b"\x00+") else 8
        if data[start:start + 30] == b"GDAL_STRUCTURAL_METADATA_SIZE=":
            names.append(name)
    return names


GHOSTED = _ghosted()


def test_the_copernicus_files_carry_gdals_ghost_header_like_the_real_tiles():
    """The pair (and GDAL's own COG) open with the ghost header the real GLO-30 tiles carry at byte 8.

    Without it the leader and trailer test below would be collected for no
    file at all and pass, leaving the trap the real tiles set untested.
    """
    for name in ("Copernicus_DSM_COG_10_N08_00_W012_00_DEM.tif", "Copernicus_DSM_COG_10_N08_00_W011_00_DEM.tif",
                 "gdal_cog_deflate_p3_f32.tif"):
        assert name in GHOSTED, name


@pytest.mark.parametrize("name", GHOSTED)
def test_gdal_block_leaders_and_trailers_lie_outside_each_blocks_byte_count(name):
    """Each block is preceded by its size and followed by its last four bytes, none of them counted.

    A reader that read the leader or the trailer as data would feed junk to
    inflate: the browser's DecompressionStream throws on it while Python's
    zlib ignores trailing bytes, so the engines would part company.
    """
    data = (DEM / name).read_bytes()
    dump = _dump(data)
    assert b"BLOCK_LEADER=SIZE_AS_UINT4" in data[:200] and b"BLOCK_TRAILER=LAST_4_BYTES_REPEATED" in data[:200]
    for directory in dump["directories"]:
        for offset, count in _blocks(directory):
            assert data[offset - 4:offset] == struct.pack("<I", count)
            assert data[offset + count:offset + count + 4] == data[offset + count - 4:offset + count]
            # the count starts at the zlib header, not at the leader
            assert data[offset] & 0x0F == 8 and (data[offset] << 8 | data[offset + 1]) % 31 == 0


@pytest.mark.parametrize("name", ["Copernicus_DSM_COG_10_N08_00_W012_00_DEM.tif",
                                  "Copernicus_DSM_COG_10_N08_00_W011_00_DEM.tif"])
def test_the_copernicus_files_put_the_full_image_first_and_its_overviews_data_before_its_own(name):
    """The full image's directory comes first and its overview's after, but the overview's tiles come first.

    That is how GDAL's COG driver lays out the real tiles, and it is the
    layout in which a reader that takes the first blocks in the file, or the
    last directory, reads the overview instead of the image.
    """
    dump = _dump((DEM / name).read_bytes())
    full, overview = dump["directories"]
    assert 254 not in full["tags"] and overview["tags"][254][1] == (1,)
    assert max(o for o, _ in _blocks(overview)) < min(o for o, _ in _blocks(full))
    assert max(d["end"] for d in dump["directories"]) < min(o for o, _ in _blocks(overview))


@pytest.mark.parametrize("name", sorted(n for n, e in FILES.items()
                                         if e.get("ifd_at_end") and e["raw"] != "terrain.ends_early"))
def test_a_directory_at_the_end_of_the_file_follows_all_of_its_data(name):
    """libtiff's default order: the strips first, the directory after them, ending the file.

    A reader that assumed every file keeps its directories in its first
    kilobytes, as a COG does, would otherwise never meet a file that does not.
    """
    data = (DEM / name).read_bytes()
    directory = _dump(data)["directories"][0]
    assert max(o + n for o, n in _blocks(directory)) <= directory["at"]
    assert directory["end"] <= len(data) <= directory["end"] + 256


@pytest.mark.parametrize("name", sorted(n for n, e in FILES.items() if e.get("bigtiff")))
def test_bigtiff_fixtures_carry_the_bigtiff_header_and_eight_byte_offsets(name):
    """Version 43, an offset size of 8, a zero, an 8-byte first offset and LONG8 block offsets.

    A BigTIFF fixture that was classic underneath would leave the reader's
    eight-byte paths untested while the manifest said otherwise.
    """
    data = (DEM / name).read_bytes()
    order = "<" if data[:2] == b"II" else ">"
    version, size, zero, first = struct.unpack_from(order + "HHHQ", data, 2)
    assert (version, size, zero) == (43, 8, 0)
    dump = _dump(data)
    assert dump["directories"][0]["at"] == first
    tags = dump["directories"][0]["tags"]
    assert tags[324 if 324 in tags else 273][0] == 16


@pytest.mark.parametrize("name", sorted(n for n, e in FILES.items()
                                         if "width" in e and e["raw"] != "terrain.ends_early"))
def test_each_file_holds_the_layout_its_manifest_entry_states(name):
    """The facts later readers are tested against are the facts in the bytes, read here by struct alone.

    If the manifest and the bytes drifted apart, the readers would be held to
    a layout no file has, and a correct reader would fail.
    """
    entry = FILES[name]
    dump = _dump((DEM / name).read_bytes())
    assert (dump["order"], dump["bigtiff"]) == (entry["byte_order"], entry["bigtiff"])
    tags = dump["directories"][entry.get("ifd_index", 0)]["tags"]
    assert (tags[256][1][0], tags[257][1][0]) == (entry["width"], entry["height"])
    assert tags[259][1][0] == entry["compression"]
    assert tags.get(317, (3, (1,)))[1][0] == entry["predictor"]
    assert tags.get(339, (3, (1,)))[1][0] == entry["sample_format"]
    assert tags[258][1][0] == entry["bits"]
    assert tags.get(277, (3, (1,)))[1][0] == entry.get("samples_per_pixel", 1)
    assert (322 in tags) == entry["tiled"]
    if entry["tiled"] and name != "refuse_zero_tile_width.tif":
        assert (tags[322][1][0], tags[323][1][0]) == (entry["block_width"], entry["block_height"])
    elif not entry["tiled"] and name != "refuse_zero_rows_per_strip.tif":
        assert tags.get(278, (4, (entry["height"],)))[1][0] == entry["rows_per_strip"]
    keys = _geokeys(tags)
    if "raster_type" in entry:
        assert keys.get(1024) == entry["model_type"]
        assert (2 if keys.get(1025) == 2 else 1) == entry["raster_type"]
        assert keys.get(2048, keys.get(3072)) == entry["epsg"]
    nodata = tags.get(42113, (2, None))[1]
    assert (None if nodata is None else nodata.rstrip(b"\x00").decode("ascii")) == entry.get("nodata")


def test_sparse_blocks_have_offset_and_byte_count_zero():
    """GDAL's sparse form, offset 0 and byte count 0, and only for the blocks the manifest names.

    A block that was merely short or empty would test a different refusal
    (a damaged block) rather than the void a sparse block must read as.
    """
    entry = FILES["sparse_f32.tif"]
    blocks = _blocks(_dump((DEM / "sparse_f32.tif").read_bytes())["directories"][0])
    assert [k for k, (o, n) in enumerate(blocks) if o == 0 and n == 0] == entry["sparse_blocks"]
    assert all(o and n for k, (o, n) in enumerate(blocks) if k not in entry["sparse_blocks"])


def test_the_deferred_clear_strip_needs_libtiffs_larger_table():
    """The strip reads with libtiff's 5,119-entry table and overflows a 4,096-entry one.

    So it is a real test of the bound: a reader whose table stops at 4,096
    refuses a strip that GDAL reads (spec section 2.6, synth2/lzw_bound.py).
    """
    data = (DEM / "lzw_deferred_clear.tif").read_bytes()
    entry = FILES["lzw_deferred_clear.tif"]
    (offset, count), = _blocks(_dump(data)["directories"][0])
    strip = data[offset:offset + count]
    expected = entry["width"] * entry["height"] * 4
    assert entry["lzw_codes_after_full_table"] == 1024
    assert _lzw(strip, expected, 5119) == _intended("lzw_deferred_clear.tif")
    with pytest.raises(ValueError, match="table is full"):
        _lzw(strip, expected, 4096)


def test_the_old_style_lzw_strip_begins_as_pre_1992_lzw_does():
    """A first byte of 0 and an odd second byte: a Clear code packed least significant bit first.

    That is the test libtiff uses to recognise the old form, so a refusal
    fixture without it would be refused for some other reason.
    """
    data = (DEM / "refuse_old_lzw.tif").read_bytes()
    (offset, _), = _blocks(_dump(data)["directories"][0])
    assert data[offset] == 0 and data[offset + 1] & 1


def test_the_padded_last_strip_inflates_to_a_full_strip_and_the_first_has_junk_after_its_stream():
    """The two DEFLATE tolerances GDAL has and spec section 2.6 keeps, in one file.

    The last strip inflates to more than its rows, and the first has bytes
    after its zlib stream; a fixture without them would let a reader that
    refuses either pass, though GDAL reads both.
    """
    data = (DEM / "padded_last_strip.tif").read_bytes()
    entry = FILES["padded_last_strip.tif"]
    blocks = _blocks(_dump(data)["directories"][0])
    full = entry["rows_per_strip"] * entry["width"] * 4
    last_rows = entry["height"] - (len(blocks) - 1) * entry["rows_per_strip"]
    offset, count = blocks[-1]
    assert len(zlib.decompress(data[offset:offset + count])) == full > last_rows * entry["width"] * 4
    offset, count = blocks[0]
    stream = zlib.decompressobj()
    assert len(stream.decompress(data[offset:offset + count])) == full
    assert stream.eof and stream.unused_data == b"GWTEND"


@pytest.mark.parametrize("name", ["pred2_none.tif", "pred2_packbits.tif"])
def test_a_predictor_tag_without_lzw_or_deflate_leaves_the_values_as_stored(name):
    """The tag says 2, but the samples are stored undifferenced, which is how libtiff and GDAL read them.

    A reader that undid the predictor here would scramble the heights while
    GDAL read them correctly.
    """
    data = (DEM / name).read_bytes()
    entry = FILES[name]
    directory = _dump(data)["directories"][0]
    assert directory["tags"][317][1] == (2,)
    stored = b"".join(data[o:o + n] for o, n in _blocks(directory))
    if entry["compression"] == 32773:
        row = entry["width"] * entry["bits"] // 8
        rows = entry["rows_per_strip"]
        stored = b"".join(_unpackbits(data[o:o + n], row * min(rows, entry["height"] - k * rows))
                          for k, (o, n) in enumerate(_blocks(directory)))
    assert stored == _intended(name)


def test_the_directory_loop_returns_to_a_directory_already_read():
    """The chain really loops, so a reader without the loop check would walk it for ever."""
    dump = _dump((DEM / "refuse_ifd_loop.tif").read_bytes())
    assert dump["loops"] and len(dump["directories"]) == 2


def test_the_renamed_copies_hold_the_copernicus_tiles_bytes():
    """n08w012.tif and n08w011.tif differ from the named tiles only in name.

    So a reader that credited them would be crediting by layout, which spec
    section 2.10 forbids: the fingerprint prompts but never credits.
    """
    for copy, source in (("n08w012.tif", "Copernicus_DSM_COG_10_N08_00_W012_00_DEM.tif"),
                         ("n08w011.tif", "Copernicus_DSM_COG_10_N08_00_W011_00_DEM.tif")):
        assert (DEM / copy).read_bytes() == (DEM / source).read_bytes()
    # only the copy whose first centre is on a whole degree fits the GLO-30 fingerprint (spec section 2.10)
    assert FILES["n08w011.tif"]["x0"] == -11.0 and FILES["n08w011.tif"]["y0"] == 9.0
    assert FILES["n08w012.tif"]["x0"] != round(FILES["n08w012.tif"]["x0"])


# --- GDAL as the oracle ------------------------------------------------------------------------

def _open(rasterio, name: str):
    path = str(DEM / name)
    index = FILES[name].get("ifd_index", 0)
    return rasterio.open(f"GTIFF_DIR:{index + 1}:{path}" if index else path)


@pytest.mark.parametrize("name", READ)
def test_gdal_reads_every_sample_the_builder_wrote_bit_for_bit(name, rasterio):
    """Bit for bit, NaN payloads and the sign of zero included, with masked=False.

    This is what stops an encoder bug (planes in the wrong byte order, a code
    widened late) from passing as a fixture the readers are then held to.
    The trap: a sparse block reads as 0 in GDAL without a no-data value, and
    the intended samples say so; the reader voids it (see the module
    docstring).
    """
    np = pytest.importorskip("numpy")
    entry = FILES[name]
    with _open(rasterio, name) as dataset:
        band = dataset.read(1, masked=False)
    dtype = np.dtype(DTYPES[entry["sample_format"], entry["bits"]]).newbyteorder("<")
    got = band.astype(dtype).tobytes()
    intended = _intended(name)
    if got != intended:
        differ = np.frombuffer(got, dtype=np.uint8) != np.frombuffer(intended, dtype=np.uint8)
        pytest.fail(f"GDAL reads {int(differ.sum())} bytes differently from what the builder meant")
    assert hashlib.sha256(got).hexdigest() == entry["samples_sha256"]


@pytest.mark.parametrize("name", READ)
def test_gdal_places_every_cell_centre_where_the_builder_meant_it(name, rasterio):
    """Within 1e-12 degree (1e-9 m when projected) of x0 + i*sx and y0 - j*sy.

    A half-cell slip between PixelIsArea and PixelIsPoint would put every
    centre about 15 m out and still open happily. Not bit for bit: GDAL
    computes (X - 0.5*Sx) + (i + 0.5)*Sx, which differs in the last bits
    from the readers' X + i*Sx for PixelIsPoint files (spec section 2.4);
    equality is held only between the two engines.
    """
    entry = FILES[name]
    tolerance = 1e-9 if entry["model_type"] == 1 else 1e-12
    with _open(rasterio, name) as dataset:
        t = dataset.transform
        assert t.b == 0 and t.d == 0
        for i in range(dataset.width):
            assert abs(t.c + (i + 0.5) * t.a - (entry["x0"] + i * entry["sx"])) <= tolerance
        for j in range(dataset.height):
            assert abs(t.f + (j + 0.5) * t.e - (entry["y0"] - j * entry["sy"])) <= tolerance


@pytest.mark.parametrize("name", READ)
def test_gdal_finds_the_coordinate_system_raster_type_and_nodata_the_builder_wrote(name, rasterio):
    """EPSG code (none without GeoKeys), PixelIsArea or PixelIsPoint, and the no-data value as spec 2.5 casts it.

    So the manifest's nodata_value, which the readers are held to, is GDAL's
    too: an empty GDAL_NODATA is no no-data value in both, and ArcGIS's
    '-3.40282346639e+038' rounds to -FLT_MAX in both.
    """
    entry = FILES[name]
    with _open(rasterio, name) as dataset:
        assert (dataset.crs.to_epsg() if dataset.crs else None) == entry["epsg"]
        assert dataset.tags().get("AREA_OR_POINT", "Area") == ("Point" if entry["raster_type"] == 2 else "Area")
        nodata = dataset.nodata
    want = entry.get("nodata_value")
    if want is None:
        assert nodata is None
    elif want == "nan":
        assert nodata is not None and math.isnan(nodata)
    elif want in ("inf", "-inf"):
        assert nodata == float(want)
    else:
        assert nodata == want


def test_the_pre_1992_lzw_file_is_genuine_because_gdal_reads_it_as_written(rasterio):
    """The reader refuses old-style LZW by choice, not because the fixture is broken: libtiff reads it.

    Were the stream garbage, the refusal test would pass for the wrong reason.
    """
    np = pytest.importorskip("numpy")
    with rasterio.open(DEM / "refuse_old_lzw.tif") as dataset:
        band = dataset.read(1, masked=False)
    assert band.astype(np.dtype("<i2")).tobytes() == _intended("refuse_old_lzw.tif")


def test_the_mask_fixtures_hold_masks_gdal_applies_over_cells_of_0(rasterio):
    """internal_mask.tif (the builder's) and gdal_internal_mask_f32.tif
    (GDAL's own) each carry a per-dataset mask GDAL applies, hiding the
    western columns, which hold 0.0: so the reader's has_mask, which both
    must set, is held to a mask GDAL would honour, not to a directory only
    the reader takes for one. Prevents the elevation layer's mask refusal
    being tested on a file no GIS would read as masked."""
    for name, hidden in (("internal_mask.tif", 4), ("gdal_internal_mask_f32.tif", 5)):
        assert FILES[name]["has_mask"] and FILES[name]["elevation"] == "terrain.internal_mask"
        with _open(rasterio, name) as dataset:
            assert [flag.name for flag in dataset.mask_flag_enums[0]] == ["per_dataset"], name
            valid = dataset.read_masks(1)
            band = dataset.read(1, masked=False)
        assert (valid[:, :hidden] == 0).all() and (valid[:, hidden:] == 255).all(), name
        assert (band[:, :hidden] == 0.0).all(), name


@pytest.mark.parametrize("text", ["-3.40282346639e+038", "3.4028235e38", "3.40283e38", "3.5e38", "1e39", "-1e39",
                                  "nan", "-inf"])
def test_a_float32_no_data_value_is_cast_and_matched_as_gdal_casts_and_masks_it(text, rasterio, tmp_path):
    """A float32 file's GDAL_NODATA is rounded to the nearest float32, as
    GDAL casts it: ArcGIS's '-3.40282346639e+038' and '3.4028235e38' to the
    largest float32, '3.40283e38' and beyond to an infinity. The reader's
    value is GDAL's after that cast, and the cells it voids are those GDAL's
    mask hides (and NaN, which the reader voids whatever the file says).
    Prevents a no-data value beyond float32 being clamped to the largest
    float32, voiding a cell GDAL keeps and keeping one GDAL hides."""
    np = pytest.importorskip("numpy")
    from groundwater.geotiff import read_geotiff

    flt_max = float(np.finfo(np.float32).max)
    rows = MAKE.metres(MAKE.patch(10, 6, 62))
    rows[0][0], rows[0][1], rows[1][0], rows[1][1], rows[2][2] = flt_max, math.inf, -math.inf, -flt_max, math.nan
    data = MAKE.single("nodata.tif", "", rows, "f32", MAKE.Georef(-11.9, 8.4, 1 / 1200, 1 / 1200), nodata=text).data
    path = tmp_path / "nodata.tif"
    path.write_bytes(data)
    with rasterio.open(path) as dataset:
        nodata = dataset.nodata
        hidden = dataset.read_masks(1) == 0
        band = dataset.read(1, masked=False)
    with np.errstate(over="ignore"):
        gdal = float(np.float32(nodata))
    raster = read_geotiff(data, "nodata.tif")
    ours = raster.layout.nodata
    assert ours == gdal or (math.isnan(ours) and math.isnan(gdal)), (ours, gdal)
    assert ours == MAKE.nodata_value(text, "f32") or math.isnan(ours)
    assert np.array_equal(np.isnan(raster.z[::-1]), hidden | np.isnan(band))
    assert hidden.any() or text == "nan", "each text matches a cell of the file"

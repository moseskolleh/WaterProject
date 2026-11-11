
  /* ===================================================== TIFF and GeoTIFF
   * groundwater/geotiff.py's reader: geotiff_layout, block_ranges,
   * decode_block and read_geotiff. It knows TIFF and GeoTIFF, not
   * elevation: it reads any sample type the toolkit takes in any coordinate
   * system, so the writer's own UTM output reads back through it, and
   * whether a grid is an elevation model the toolkit can use is the
   * elevation layer's question.
   *
   * It reads in two steps, so that a page never has to hold a whole file:
   * geotiffLayout learns where everything lies from the bytes it has been
   * given and names the ranges it still needs, and decodeTiffBlock turns
   * one block's bytes into values, so a window decodes only the blocks it
   * meets (blockRanges). Everything is synchronous and Uint8Array in,
   * typed arrays out, for the worker and the Node sandboxes alike.
   * Multi-byte values are read through a DataView in the file's own byte
   * order; a 64-bit one is read as two 32-bit halves, because a value at or
   * past 2^53 is no offset or count a number holds exactly, and the halves
   * show that without BigInt. Each refusal is a catalogued sentence, thrown
   * by tiffError with the id Python raises. */

  /** @typedef {Record<string, any>} TiffLayout  what geotiffLayout returns */
  /** @typedef {[number, number, number, [number, number]|null]} TiffRange  [block, offset, length, rows] */

  /** A refusal as the reader makes it, the twin of geotiff.GeoTiffError:
   * an Error whose message is the catalogued sentence, carrying the id
   * (`ident`), the id without its 'terrain.' prefix (`code`) and the values
   * the sentence was given (`values`).
   * @param {string} ident the sentence's full id, such as 'terrain.not_tiff'
   * @param {Record<string, *>} values what fills the sentence
   * @returns {Error}
   */
  function tiffError(ident, values) {
    var error = /** @type {Error & {ident: string, code: string, values: Record<string, *>}} */ (
      new Error(phrase(ident, values)));
    error.ident = ident;
    error.code = ident.slice(ident.indexOf('.') + 1);
    error.values = values;
    return error;
  }

  /* The tags the reader reads, each with the name the bad_tag sentence
   * gives it, what it holds (whole numbers, real numbers, the GeoKey
   * directory's shorts, or text) and how many values it may have: exactly
   * one ('one', as libtiff reads them), at least one with the first read
   * ('first', given per sample), or any number, none included ('any'). */
  var TIFF_TAGS = {
    254: ['NewSubfileType', 'int', 'one'], 255: ['SubfileType', 'int', 'one'],
    256: ['ImageWidth', 'int', 'one'], 257: ['ImageLength', 'int', 'one'],
    258: ['BitsPerSample', 'int', 'first'], 259: ['Compression', 'int', 'one'],
    266: ['FillOrder', 'int', 'one'], 273: ['StripOffsets', 'int', 'any'],
    277: ['SamplesPerPixel', 'int', 'one'], 278: ['RowsPerStrip', 'int', 'one'],
    279: ['StripByteCounts', 'int', 'any'], 284: ['PlanarConfiguration', 'int', 'one'],
    317: ['Predictor', 'int', 'one'], 322: ['TileWidth', 'int', 'one'],
    323: ['TileLength', 'int', 'one'], 324: ['TileOffsets', 'int', 'any'],
    325: ['TileByteCounts', 'int', 'any'], 339: ['SampleFormat', 'int', 'first'],
    33550: ['ModelPixelScale', 'real', 'any'], 33922: ['ModelTiepoint', 'real', 'any'],
    34264: ['ModelTransformation', 'real', 'any'], 34735: ['GeoKeyDirectory', 'short', 'any'],
    34736: ['GeoDoubleParams', 'real', 'any'], 34737: ['GeoAsciiParams', 'text', 'any'],
    42112: ['GDAL_METADATA', 'text', 'any'], 42113: ['GDAL_NODATA', 'text', 'any'],
  };
  /* the image directory's tags, read in this order, so that the first
   * damaged one is the one named whichever engine reads it */
  var TIFF_READ = [256, 257, 258, 259, 266, 273, 277, 278, 279, 284, 317, 322, 323, 324, 325,
    339, 33550, 33922, 34264, 34735, 34736, 34737, 42112, 42113];
  /* bytes per value of each TIFF field type; 0 for a type the reader does
   * not know (13, IFD, among them), which TIFF 6.0 tells a reader to skip:
   * an entry of such a type is passed over, unless the reader needs it */
  var TIFF_TYPE_SIZE = [0, 1, 1, 2, 4, 8, 1, 1, 2, 4, 8, 4, 8, 0, 0, 0, 8, 8, 8];
  /* The field types each kind of tag may have; any other is a damaged
   * entry, in both engines. These are the types TIFF and GeoTIFF give each
   * tag: an unsigned integer as BYTE, SHORT or LONG (TIFF 6.0 tells readers
   * to take any of the three) or BigTIFF's LONG8, never a signed or IFD
   * type; the GeoTIFF reals as DOUBLE; the GeoKey directory as SHORT; text
   * as ASCII. libtiff converts more, but a file written otherwise is not
   * one GDAL or any GeoTIFF writer makes, and refusing it is the simpler
   * rule. */
  var TIFF_KIND_TYPES = { int: [1, 3, 4, 16], real: [12], short: [3], text: [2] };
  /* the GeoKeys read: model type, raster type, geographic CRS, datum,
   * angular unit and projected CRS */
  var TIFF_GEOKEYS = [1024, 1025, 2048, 2050, 2054, 3072];
  var TIFF_SAMPLE_KINDS = { 1: 'unsigned integer', 2: 'signed integer', 3: 'floating-point' };
  /* the (SampleFormat, BitsPerSample) pairs the reader takes */
  var TIFF_SAMPLE_TYPES = [[1, 8], [2, 8], [1, 16], [2, 16], [1, 32], [2, 32], [3, 32], [3, 64]];
  var TIFF_COMPRESSIONS = [1, 5, 8, 32946, 32773];
  /* the largest block decoded whole: a block is held in memory at once */
  var TIFF_BLOCK_LIMIT = 64 * 1048576;
  /* the block tables, each held to terrain.max_blocks before its values
   * are read */
  var TIFF_BLOCK_TABLES = [273, 279, 324, 325];

  /* An unsigned 64-bit field, as two 32-bit halves. At or past 2^53 it is
   * no offset or count a number holds exactly, and the file is refused
   * there rather than read somewhere else. */
  function tiffU64(view, at, little, name) {
    var lo = view.getUint32(at + (little ? 0 : 4), little);
    var hi = view.getUint32(at + (little ? 4 : 0), little);
    if (hi >= 0x200000) throw tiffError('terrain.too_large', { file: name });
    return hi * 4294967296 + lo;
  }

  /* `count` values of field type `type` (one TIFF_KIND_TYPES allows) from
   * `at`: numbers, or for ASCII the bytes as one string, a character a byte
   * (Latin-1, as Python reads them). A LONG8 value of 2^53 or more is
   * refused as it is read. */
  function tiffFieldValues(view, at, type, count, little, name) {
    var i, p, size = TIFF_TYPE_SIZE[type];
    if (type === 2) {
      var text = '';
      for (i = 0; i < count; i++) text += String.fromCharCode(view.getUint8(at + i));
      return text;
    }
    var out = new Array(count);
    for (i = 0, p = at; i < count; i++, p += size) {
      switch (type) {
        case 1: out[i] = view.getUint8(p); break;
        case 3: out[i] = view.getUint16(p, little); break;
        case 4: out[i] = view.getUint32(p, little); break;
        case 12: out[i] = view.getFloat64(p, little); break;
        default: out[i] = tiffU64(view, p, little, name);   // 16, LONG8
      }
    }
    return out;
  }

  /* `text` with any of the characters in `blanks` trimmed from its end, and
   * from its start too unless `endOnly`: as Python's str.strip and rstrip */
  function tiffTrim(text, blanks, endOnly) {
    var start = 0, end = text.length;
    while (!endOnly && start < end && blanks.indexOf(text.charAt(start)) >= 0) start++;
    while (end > start && blanks.indexOf(text.charAt(end - 1)) >= 0) end--;
    return text.slice(start, end);
  }
  /* NULs and ASCII white space, which a no-data value is trimmed of */
  var TIFF_BLANKS = '\0 \t\n\r';

  /* GDAL_NODATA's number rule, which GDAL_METADATA's scale and offset are
   * read by too: NULs and ASCII white space trimmed, then the words GDAL
   * writes for NaN and the infinities, then a plain decimal number, read
   * correctly rounded as Python's float() reads it. null for empty text,
   * undefined for text that is not a number. */
  function tiffNumber(text) {
    var s = tiffTrim(text, TIFF_BLANKS, false), low = s.toLowerCase();
    if (s === '') return null;
    if (low === 'nan' || low === '+nan' || low === '-nan') return NaN;
    if (low === 'inf' || low === '+inf' || low === 'infinity' || low === '+infinity') return Infinity;
    if (low === '-inf' || low === '-infinity') return -Infinity;
    if (/^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$/.test(s)) return Number(s);
    return undefined;
  }

  /* A no-data value as a sample of the file's type holds it: float32
   * rounded to the nearest float32, as GDAL casts it, so one beyond the
   * largest float32 by more than half a step is an infinity (ArcGIS's
   * -3.40282346639e+038 lies within half a step and rounds to the largest
   * on its own); float64 as read; for an integer type only a whole number
   * in range, else null, since then no cell can hold it. */
  function tiffNodataCast(value, format, bits) {
    if (format === 3 && bits === 32) return Math.fround(value);
    if (format === 3) return value;
    var low = format === 1 ? 0 : -Math.pow(2, bits - 1);
    var high = format === 1 ? Math.pow(2, bits) - 1 : Math.pow(2, bits - 1) - 1;
    return Number.isInteger(value) && value >= low && value <= high ? value + 0 : null;
  }

  /** Where everything in a GeoTIFF lies, from the bytes read so far, as
   * geotiff.geotiff_layout gives it - the image's size, sample type,
   * compression and predictor, its blocks and where each lies, its
   * coordinate system, the centres of its first column and row (row 0 the
   * northernmost) and its cell sizes, and its no-data value - or, when
   * bytes it needs have not been read, the sorted list of [offset, length]
   * ranges to read next and pass back with the rest. The header is the
   * first 16 bytes; the directory chain is followed from there to the first
   * full-resolution image (overviews and masks are passed by, at most 64
   * directories); then every value of that image's tags that lies outside
   * its directory is read. The image is checked - dimensions, samples to a
   * cell, sample type, compression, predictor, fill order, block table,
   * block size, in that order - before its georeferencing, no-data value
   * and GDAL scale and offset are read; last, the directory after it is
   * read to see whether it is a GDAL mask of the image (hasMask), which the
   * reader notes but does not apply. A block table longer than
   * terrain.max_blocks is refused before its values are read. A range past
   * the end of the file is refused as an incomplete file, never asked for.
   * @param {string} name the file's name, as the sentences give it
   * @param {number} size the file's length in bytes
   * @param {Array<[number, Uint8Array]>} chunks the bytes read so far, as [offset, bytes]
   * @returns {TiffLayout|Array<[number, number]>}
   */
  function geotiffLayout(name, size, chunks) {
    /** @type {Array<[number, number]>} */
    var need = [];

    /* bytes [off, off + n) as a DataView, when one chunk holds them all;
     * otherwise the range joins those still needed and null comes back */
    function at(off, n, part) {
      if (off + n > size) throw tiffError('terrain.ends_early', { file: name, part: part });
      for (var k = 0; k < chunks.length; k++) {
        var start = chunks[k][0], bytes = chunks[k][1];
        if (start <= off && off + n <= start + bytes.length) {
          return new DataView(bytes.buffer, bytes.byteOffset + (off - start), n);
        }
      }
      need.push([off, n]);
      return null;
    }

    function needed() {
      need.sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; });
      return need.filter(function (range, k) {
        return k === 0 || range[0] !== need[k - 1][0] || range[1] !== need[k - 1][1];
      });
    }

    var head = at(0, 16, 'file header');
    if (!head) return needed();
    var mark = head.getUint16(0, false), little;
    if (mark === 0x4949) little = true;
    else if (mark === 0x4D4D) little = false;
    else throw tiffError('terrain.not_tiff', { file: name });
    var version = head.getUint16(2, little), big = version === 43, ifd;
    if (version === 42) ifd = head.getUint32(4, little);
    else if (big && head.getUint16(4, little) === 8 && head.getUint16(6, little) === 0) {
      ifd = tiffU64(head, 8, little, name);
    } else {
      throw tiffError('terrain.not_tiff', { file: name });
    }
    var countSize = big ? 8 : 2, entrySize = big ? 20 : 12, word = big ? 8 : 4;

    /* the directory in hand: where each tag's first entry starts, its
     * type, and the directory's bytes. Only the entries of the tags the
     * reader reads are examined; any other is passed over, whatever its
     * type or count, as libtiff passes over a tag it does not use. */
    var entries = {}, body = head, index = -1, seen = [], n = 0, e;

    /* Make the directory at `where` the one in hand: its entry count `n`,
     * its bytes (the entries and the next pointer) and each tag's first
     * entry, a repeated tag's first counting, as libtiff has it. False
     * while its bytes are still needed. */
    function enter(where) {
      var counted = at(where, countSize, 'image directory');
      if (!counted) return false;
      n = big ? tiffU64(counted, 0, little, name) : counted.getUint16(0, little);
      var read = at(where + countSize, n * entrySize + word, 'image directory');
      if (!read) return false;
      body = read;
      entries = {};
      for (e = 0; e < n; e++) {
        var p = e * entrySize, tag = body.getUint16(p, little);
        if (own(entries, tag)) continue;
        entries[tag] = { type: body.getUint16(p + 2, little), at: p };
      }
      return true;
    }

    /* A tag's entry in the directory in hand, judged in this order in both
     * engines: its type, then (BigTIFF) a count of 2^53 or more, then its
     * count. Returns its type, count, byte length and where its value
     * field lies in the directory. */
    function checked(tag) {
      var spec = TIFF_TAGS[tag], p = entries[tag].at, type = entries[tag].type;
      if (TIFF_KIND_TYPES[spec[1]].indexOf(type) < 0) {
        throw tiffError('terrain.bad_tag', { file: name, tag: spec[0] });
      }
      var count = big ? tiffU64(body, p + 4, little, name) : body.getUint32(p + 4, little);
      if ((spec[2] === 'one' && count !== 1) || (spec[2] === 'first' && count < 1)) {
        throw tiffError('terrain.bad_tag', { file: name, tag: spec[0] });
      }
      return { type: type, count: count, length: count * TIFF_TYPE_SIZE[type], field: p + (big ? 12 : 8) };
    }

    /* NewSubfileType or SubfileType, NewSubfileType judged first. One of a
     * field type TIFF does not define is skipped, as TIFF 6.0 tells a reader
     * to skip it, and counts as absent (null); one of a known type must be
     * an unsigned integer type, one value, held in the entry itself (a
     * LONG8 is not, in a classic TIFF), or the entry is damaged. */
    function subfile(tag) {
      if (!own(entries, tag) || !TIFF_TYPE_SIZE[entries[tag].type]) return null;
      var entry = checked(tag);
      if (entry.length > word) throw tiffError('terrain.bad_tag', { file: name, tag: TIFF_TAGS[tag][0] });
      return tiffFieldValues(body, entry.field, entry.type, 1, little, name)[0];
    }

    for (;;) {
      /* The next pointer is judged in this order in both engines: 0 ends
       * the chain, then 2^53 or more is too large (refused by tiffU64 as it
       * is read below, which cannot clash with 0), then a directory already
       * walked is a loop, then a 65th directory is not walked. */
      if (ifd === 0) throw tiffError('terrain.no_full_image', { file: name });
      if (seen.indexOf(ifd) >= 0) throw tiffError('terrain.directory_loop', { file: name });
      if (seen.length === 64) throw tiffError('terrain.no_full_image', { file: name });
      seen.push(ifd);
      index++;
      if (!enter(ifd)) return needed();
      var newer = subfile(254), older = subfile(255);
      /* full resolution: neither a reduced image (bit 0) nor a mask (bit 2)
       * by NewSubfileType, nor a reduced image (2) by the old SubfileType;
       * its next pointer is looked at only for its mask, once the image is
       * described */
      if (!((newer || 0) & 5) && older !== 2 && own(entries, 256) && own(entries, 257)) break;
      ifd = big ? tiffU64(body, n * entrySize, little, name) : body.getUint32(n * entrySize, little);
    }

    /* The chosen directory's entries, in ascending tag order, each judged
     * in this order in both engines: its type, then (BigTIFF) a count of
     * 2^53 or more, then its count, then a block table longer than
     * terrain.max_blocks (the default: the reader takes no configuration),
     * then an out-of-line offset of 2^53 or more, then values running past
     * the end of the file. Values not yet read are asked for together once
     * every entry has passed, since none depends on another, so the refusal
     * a file earns does not depend on how it was read. A block table is
     * held to the cap before its values are asked for, so that opening a
     * file never reads or builds millions of offsets. */
    /** @type {Array<[number, DataView, number, {type: number, count: number}]>} */
    var held = [];
    var maxBlocks = withConfig(null).terrain.max_blocks;
    TIFF_READ.forEach(function (tag) {
      if (!own(entries, tag)) return;
      var entry = checked(tag), view = /** @type {DataView|null} */ (body), pos = entry.field;
      if (TIFF_BLOCK_TABLES.indexOf(tag) >= 0 && entry.count > maxBlocks) {
        throw tiffError('terrain.too_many_blocks', { file: name, n: entry.count, cap: maxBlocks });
      }
      if (entry.length > word) {
        view = at(big ? tiffU64(body, pos, little, name) : body.getUint32(pos, little),
          entry.length, 'values of ' + TIFF_TAGS[tag][0]);
        pos = 0;
      }
      if (view) held.push([tag, view, pos, entry]);
    });
    if (need.length) return needed();
    /* Then every value is decoded, tag by tag in ascending order, before any
     * check reads one: a LONG8 value of 2^53 or more is refused here, ahead
     * of every check on what the values mean. An absent tag is null. */
    /** @type {Record<number, any>} */
    var v = {};
    TIFF_READ.forEach(function (tag) { v[tag] = null; });
    held.forEach(function (h) {
      v[h[0]] = tiffFieldValues(h[1], h[2], h[3].type, h[3].count, little, name);
    });
    function first(tag, absent) {
      return v[tag] ? v[tag][0] : absent;
    }

    /* dimensions, before anything is divided by them */
    var width = first(256, 0), height = first(257, 0);
    if (width < 1) throw tiffError('terrain.bad_tag', { file: name, tag: 'ImageWidth' });
    if (height < 1) throw tiffError('terrain.bad_tag', { file: name, tag: 'ImageLength' });
    var tiled = !!(v[322] || v[323]), blockWidth, blockHeight, rowsPerStrip = null;
    if (tiled) {
      blockWidth = first(322, 0);
      blockHeight = first(323, 0);
      if (blockWidth < 1) throw tiffError('terrain.bad_tag', { file: name, tag: 'TileWidth' });
      if (blockHeight < 1) throw tiffError('terrain.bad_tag', { file: name, tag: 'TileLength' });
    } else {
      /* absent, 2^32 - 1 (libtiff's "the whole image") or past the image:
       * one strip; 2^32 - 1 is named because a LONG8 height may pass it */
      rowsPerStrip = first(278, height);
      if (rowsPerStrip === 0xFFFFFFFF) rowsPerStrip = height;
      rowsPerStrip = Math.min(rowsPerStrip, height);
      if (rowsPerStrip < 1) throw tiffError('terrain.bad_tag', { file: name, tag: 'RowsPerStrip' });
      blockWidth = width;
      blockHeight = rowsPerStrip;
    }
    var samples = first(277, 1);
    if (samples !== 1) throw tiffError('terrain.bands', { file: name, n: samples });
    /* an absent SampleFormat is unsigned, as the TIFF rule and GDAL have
     * it; the pair is matched as a pair, since folded into one number
     * SampleFormat 1 with 108 bits would pass for 2 with 8 */
    var bits = first(258, 1), format = first(339, 1);
    if (!TIFF_SAMPLE_TYPES.some(function (t) { return t[0] === format && t[1] === bits; })) {
      throw tiffError('terrain.sample_type', {
        file: name, bits: bits,
        kind: own(TIFF_SAMPLE_KINDS, format) ? TIFF_SAMPLE_KINDS[format] : 'SampleFormat ' + format,
      });
    }
    var compression = first(259, 1);
    if (TIFF_COMPRESSIONS.indexOf(compression) < 0) {
      var methods = phraseTable('terrain.compression_names');
      throw tiffError('terrain.compression', {
        file: name,
        method: own(methods, String(compression)) ? methods[String(compression)] :
          'TIFF method ' + compression,
      });
    }
    /* libtiff sets a predictor up only inside its LZW and DEFLATE codecs, so
     * with no compression or PackBits the tag is ignored, its value
     * unexamined, and GDAL reads the values as they are stored; with LZW or
     * DEFLATE it must be 1, 2 or 3, and 3 needs floating-point samples */
    var predictor = first(317, 1);
    var coded = compression === 5 || compression === 8 || compression === 32946;
    if (coded && ([1, 2, 3].indexOf(predictor) < 0 || (predictor === 3 && format !== 3))) {
      throw tiffError('terrain.predictor', { file: name, code: predictor });
    }
    /* FillOrder 2 is refused by name; any value but 1 or 2 is one libtiff
     * rejects as a bad value, so a damaged entry */
    var fillOrder = first(266, 1);
    if (fillOrder === 2) throw tiffError('terrain.fill_order', { file: name });
    if (fillOrder !== 1) throw tiffError('terrain.bad_tag', { file: name, tag: 'FillOrder' });
    var blocks = (tiled ? Math.ceil(width / blockWidth) : 1) * Math.ceil(height / blockHeight);
    var offsets = v[tiled ? 324 : 273] || [], byteCounts = v[tiled ? 325 : 279] || [];
    if (offsets.length !== blocks) {
      throw tiffError('terrain.bad_tag', { file: name, tag: tiled ? 'TileOffsets' : 'StripOffsets' });
    }
    if (byteCounts.length !== blocks) {
      throw tiffError('terrain.bad_tag', { file: name, tag: tiled ? 'TileByteCounts' : 'StripByteCounts' });
    }
    var full = blockWidth * blockHeight * (bits / 8);
    if (full > TIFF_BLOCK_LIMIT) {
      throw tiffError('terrain.block_too_large', { file: name, mb: full / 1048576 });
    }

    /* GeoKeys. Every key read holds a SHORT, so only one stored in the
     * directory itself (location 0) is taken, as libgeotiff reads a SHORT
     * key; the first of a repeated key counts. A directory of fewer than
     * four values, of a version other than 1 (the only one GeoTIFF
     * defines; libgeotiff refuses later ones) or shorter than its keys is
     * damaged. */
    /** @type {Record<number, number>} */
    var keys = {};
    var directory = v[34735];
    if (directory) {
      if (directory.length < 4 || directory[0] !== 1 || 4 + 4 * directory[3] > directory.length) {
        throw tiffError('terrain.bad_tag', { file: name, tag: 'GeoKeyDirectory' });
      }
      for (e = 0; e < directory[3]; e++) {
        var key = directory[4 + 4 * e];
        if (TIFF_GEOKEYS.indexOf(key) >= 0 && !own(keys, key) && directory[5 + 4 * e] === 0) {
          keys[key] = directory[7 + 4 * e];
        }
      }
    }
    function geokey(key) {
      return own(keys, key) ? keys[key] : null;
    }
    /* PixelIsPoint only when the key says 2; absent, 0 or anything else is
     * area, as GDAL reads it */
    var modelType = geokey(1024), rasterType = geokey(1025) === 2 ? 2 : 1;
    var epsg = geokey(modelType === 1 ? 3072 : 2048);

    /* Scale and tiepoint first, as GDAL reads them; a transformation only
     * when there is no scale; several tiepoints alone place the grid by
     * control points. A scale, when there is one, is judged in this order
     * in both engines: fewer than two values is a damaged entry, then no
     * tiepoint places nothing, then a tiepoint of fewer than six values is
     * damaged, then a scale that is not positive is a flipped grid. */
    var scale = v[33550], tie = v[33922], matrix = v[34264], sx, sy, col, row, x, y;
    if (scale) {
      if (scale.length < 2) throw tiffError('terrain.bad_tag', { file: name, tag: 'ModelPixelScale' });
      if (!tie) throw tiffError('terrain.no_georeference', { file: name });
      if (tie.length < 6) throw tiffError('terrain.bad_tag', { file: name, tag: 'ModelTiepoint' });
      sx = scale[0];
      sy = scale[1];
      col = tie[0];
      row = tie[1];
      x = tie[3];
      y = tie[4];
      if (!(sx > 0 && sy > 0)) throw tiffError('terrain.rotated', { file: name });
    } else if (matrix) {
      if (matrix.length !== 16) {
        throw tiffError('terrain.bad_tag', { file: name, tag: 'ModelTransformation' });
      }
      if (!(matrix[1] === 0 && matrix[4] === 0 && matrix[0] > 0 && matrix[5] < 0)) {
        throw tiffError('terrain.rotated', { file: name });
      }
      sx = matrix[0];
      sy = -matrix[5];
      col = 0;
      row = 0;
      x = matrix[3];
      y = matrix[7];
    } else if (tie && tie.length >= 12) {
      throw tiffError('terrain.control_points', { file: name });
    } else {
      throw tiffError('terrain.no_georeference', { file: name });
    }
    /* the centre of column 0 and of row 0 (north): PixelIsArea puts the
     * tiepoint at a cell's corner, PixelIsPoint at its centre. Integer
     * times double, then add, in this order in both engines. */
    var area = rasterType !== 2;
    var x0 = (x - col * sx) + (area ? 0.5 * sx : 0.0);
    var y0 = (y + row * sy) - (area ? 0.5 * sy : 0.0);

    /* Float no-data keeps the sign of a zero (-0 still matches every zero);
     * an integer one that no sample can equal is null */
    var nodata = null, nodataText = v[42113];
    if (nodataText !== null) {
      var number = tiffNumber(nodataText);
      if (number === undefined) {
        throw tiffError('terrain.nodata_unreadable', {
          file: name, text: tiffTrim(nodataText, TIFF_BLANKS, false),
        });
      }
      if (number !== null) nodata = tiffNodataCast(number, format, bits);
    }
    /* a scale or offset that is empty, not a number or NaN is refused too:
     * only an exact 1 and 0 (-0 included) are no scaling */
    var metadata = v[42112];
    if (metadata !== null) {
      var item = /<Item[^>]*role="(scale|offset)"[^>]*>([^<]*)<\/Item>/g, found;
      while ((found = item.exec(metadata)) !== null) {
        var factor = tiffNumber(found[2]);
        if (factor === null || factor === undefined || factor !== (found[1] === 'scale' ? 1 : 0)) {
          throw tiffError('terrain.scaled', { file: name });
        }
      }
    }

    /* Last, once the image has passed every check, the directory after it:
     * GDAL writes a mask of the image's cells there (masks before the image
     * belong to other images, and are passed by as the chain is walked).
     * Its next pointer is judged as the chain judges one, in the same order
     * in both engines: 0 is no mask, then 2^53 or more is too large
     * (refused by tiffU64 as it is read), then a directory already walked is
     * no mask. The mask's NewSubfileType, then its width and its height,
     * are each read as the chain reads NewSubfileType, held in the entry. */
    var geoAscii = v[34737] === null ? null : tiffTrim(v[34737], '\0', true);
    var hasMask = false;
    var following = big ? tiffU64(body, n * entrySize, little, name) : body.getUint32(n * entrySize, little);
    if (following !== 0 && seen.indexOf(following) < 0) {
      if (!enter(following)) return needed();
      var mask = subfile(254);
      hasMask = mask !== null && (mask & 5) === 4 && subfile(256) === width && subfile(257) === height;
    }

    return {
      name: name, size: size, byteOrder: little ? '<' : '>', bigtiff: big,
      width: width, height: height, bits: bits, sampleFormat: format,
      compression: compression, predictor: predictor, predictorApplied: coded && predictor !== 1,
      tiled: tiled, blockWidth: blockWidth, blockHeight: blockHeight, rowsPerStrip: rowsPerStrip,
      offsets: offsets.slice(), byteCounts: byteCounts.slice(),
      modelType: modelType, rasterType: rasterType, epsg: epsg,
      datum: geokey(2050), angularUnit: geokey(2054),
      x0: x0, y0: y0, sx: sx, sy: sy, nodata: nodata, ifdIndex: index,
      geoAscii: geoAscii, hasNodataTag: nodataText !== null, hasMask: hasMask,
    };
  }

  /* Where block `index` lies: its first image row and column, the rows it
   * decodes to (a tile's whole height, padding included; a strip's own
   * rows), and the rows and columns of it inside the image. */
  function tiffBlockBox(layout, index) {
    var across = layout.tiled ? Math.ceil(layout.width / layout.blockWidth) : 1;
    var top = Math.floor(index / across) * layout.blockHeight;
    var left = (index % across) * layout.blockWidth;
    var rows = Math.min(layout.blockHeight, layout.height - top);
    return {
      top: top, left: left, decoded: layout.tiled ? layout.blockHeight : rows,
      rows: rows, cols: Math.min(layout.blockWidth, layout.width - left),
    };
  }

  /** The blocks holding rows [j0, j1) and columns [i0, i1) of the image
   * (north row 0, half-open; clipped to the image), in the file's block
   * order, as geotiff.block_ranges lists them: [block, offset, length,
   * rows], the bytes to read for each. rows is null except for an
   * uncompressed strip only part of which is wanted: then it is the
   * strip's own half-open [r0, r1], and the range covers only those rows,
   * since an uncompressed strip never carries an applied predictor and a
   * part of it decodes as the whole does. A sparse block (offset and
   * length 0) is listed too, with nothing to read. A range reaching past
   * the end of the file is refused as an incomplete file.
   * @param {TiffLayout} layout what geotiffLayout returned
   * @param {number} j0 the first row, north first
   * @param {number} j1 the row after the last
   * @param {number} i0 the first column
   * @param {number} i1 the column after the last
   * @returns {Array<TiffRange>}
   */
  function blockRanges(layout, j0, j1, i0, i1) {
    var width = layout.width, height = layout.height;
    j0 = Math.max(0, j0);
    j1 = Math.min(height, j1);
    i0 = Math.max(0, i0);
    i1 = Math.min(width, i1);
    /** @type {Array<TiffRange>} */
    var out = [];
    if (j1 <= j0 || i1 <= i0) return out;
    var bw = layout.blockWidth, bh = layout.blockHeight, ty, tx, k;
    if (layout.tiled) {
      var across = Math.ceil(width / bw);
      for (ty = Math.floor(j0 / bh); ty <= Math.floor((j1 - 1) / bh); ty++) {
        for (tx = Math.floor(i0 / bw); tx <= Math.floor((i1 - 1) / bw); tx++) {
          k = ty * across + tx;
          out.push([k, layout.offsets[k], layout.byteCounts[k], null]);
        }
      }
    } else {
      var rowBytes = width * (layout.bits / 8);
      for (k = Math.floor(j0 / bh); k <= Math.floor((j1 - 1) / bh); k++) {
        var top = k * bh, rows = Math.min(bh, height - top);
        var r0 = Math.max(j0 - top, 0), r1 = Math.min(j1 - top, rows);
        var sparse = layout.offsets[k] === 0 && layout.byteCounts[k] === 0;
        if (layout.compression === 1 && (r0 > 0 || r1 < rows)) {
          out.push(sparse ? [k, 0, 0, [r0, r1]] :
            [k, layout.offsets[k] + r0 * rowBytes, (r1 - r0) * rowBytes, [r0, r1]]);
        } else {
          out.push([k, layout.offsets[k], layout.byteCounts[k], null]);
        }
      }
    }
    /* the block as stored must lie in the file even when only some of its
     * rows are read, so a part is refused where the whole would be; a
     * sparse block has no bytes to lie anywhere */
    out.forEach(function (range) {
      var offset = layout.offsets[range[0]], count = layout.byteCounts[range[0]];
      if (!(offset === 0 && count === 0) && offset + count > layout.size) {
        throw tiffError('terrain.ends_early', { file: layout.name, part: 'data block ' + (range[0] + 1) });
      }
    });
    return out;
  }

  /* Predictor 2 undone in place on the first `rows` rows of a decoded
   * block: each word of `size` bytes, read in the file's byte order, plus
   * the one before it, modulo the word. A 64-bit word is two 32-bit halves
   * with the carry taken across by hand. Float samples are added as their
   * bit patterns, as FABDEM's are written. Only the `cols` words inside
   * the image are needed, since each depends only on those before it. */
  function tiffUndoHorizontal(data, view, rows, rowBytes, cols, size, little) {
    var r, c, p, q, prev, now, lo, hi, plo, phi;
    var loAt = little ? 0 : 4, hiAt = little ? 4 : 0;
    for (r = 0; r < rows; r++) {
      p = r * rowBytes;
      if (size === 1) {
        for (c = 1; c < cols; c++) data[p + c] = (data[p + c] + data[p + c - 1]) & 255;
      } else if (size === 2) {
        prev = view.getUint16(p, little);
        for (c = 1; c < cols; c++) {
          now = (view.getUint16(p + 2 * c, little) + prev) & 0xFFFF;
          view.setUint16(p + 2 * c, now, little);
          prev = now;
        }
      } else if (size === 4) {
        prev = view.getUint32(p, little);
        for (c = 1; c < cols; c++) {
          now = (view.getUint32(p + 4 * c, little) + prev) >>> 0;
          view.setUint32(p + 4 * c, now, little);
          prev = now;
        }
      } else {
        plo = view.getUint32(p + loAt, little);
        phi = view.getUint32(p + hiAt, little);
        for (c = 1; c < cols; c++) {
          q = p + 8 * c;
          lo = (view.getUint32(q + loAt, little) + plo) >>> 0;
          hi = (view.getUint32(q + hiAt, little) + phi + (lo < plo ? 1 : 0)) >>> 0;
          view.setUint32(q + loAt, lo, little);
          view.setUint32(q + hiAt, hi, little);
          plo = lo;
          phi = hi;
        }
      }
    }
  }

  /** One block's values, as geotiff.decode_block gives them: rows north
   * first, the padding of an edge tile cropped, and each sample judged
   * before anything else uses it. A sample matching the no-data value, or NaN,
   * has reason 1 (no data); with `bounds`, one that is infinite or lies
   * outside them has reason 2 (implausible); both are NaN in `values`.
   * Every other sample is widened to a double exactly and canonicalised
   * with v + 0, so -0 reads as +0, with reason 0. Without bounds (the raw
   * layer) only no data and NaN are voided. A sparse block is all reason
   * 1: GDAL reads it as 0, but a block that holds no data is not ground at
   * 0 m. A block that does not decode is refused with the one damaged-block
   * sentence, numbered from 1 in the file's block order.
   * @param {TiffLayout} layout what geotiffLayout returned
   * @param {number} index the block, in the file's block order from 0
   * @param {Uint8Array} bytes what blockRanges said to read for it
   * @param {[number, number]|null} [rows] the rows blockRanges listed for an uncompressed strip read in part
   * @param {[number, number]|null} [bounds] the lowest and highest plausible value, or null for none
   * @returns {{values: Float64Array, reasons: Uint8Array, rows: number, cols: number}}
   */
  function decodeTiffBlock(layout, index, bytes, rows, bounds) {
    var box = tiffBlockBox(layout, index), size = layout.bits / 8;
    var rowBytes = layout.blockWidth * size;
    var expected = box.decoded * rowBytes, full = layout.blockHeight * rowBytes;
    var r0 = 0, r1 = box.rows, cols = box.cols;
    if (rows) {
      /* rows only of an uncompressed strip, and within it, as blockRanges gives them */
      if (layout.tiled || layout.compression !== 1 || !(rows[0] >= 0 && rows[0] < rows[1] && rows[1] <= box.rows)) {
        throw new Error('decodeTiffBlock: rows ' + JSON.stringify(rows) + ' are not rows of uncompressed strip ' +
          index);
      }
      r0 = rows[0];
      r1 = rows[1];
    }
    var n = (r1 - r0) * cols;
    var values = new Float64Array(n), reasons = new Uint8Array(n);
    if (layout.offsets[index] === 0 && layout.byteCounts[index] === 0) {
      values.fill(NaN);
      reasons.fill(1);
      return { values: values, reasons: reasons, rows: r1 - r0, cols: cols };
    }
    var data;
    try {
      if (layout.compression === 1) {
        /* the stored count is held to the whole block even when part of it
         * is read; the data given must hold the whole block (a tile's
         * padding included) or the rows asked for */
        if (layout.byteCounts[index] < expected || bytes.length < (rows ? (r1 - r0) * rowBytes : expected)) {
          throw codecError('damaged');
        }
        data = bytes;
      } else if (layout.compression === 5) {
        data = lzwDecode(bytes, expected);
      } else if (layout.compression === 32773) {
        data = packbitsDecode(bytes, expected);
      } else {
        data = inflateZlib(bytes, expected, full);
      }
    } catch (e) {
      if (e.code === 'old_lzw') throw tiffError('terrain.old_lzw', { file: layout.name });
      if (e.code === 'damaged') {
        throw tiffError('terrain.block_damaged', { n: index + 1, file: layout.name, bytes: expected });
      }
      throw e;
    }
    var little = layout.byteOrder === '<';
    var view = new DataView(data.buffer, data.byteOffset, data.byteLength);
    var floating = layout.predictorApplied && layout.predictor === 3;
    if (layout.predictorApplied && layout.predictor === 2) {
      tiffUndoHorizontal(data, view, box.rows, rowBytes, cols, size, little);
    }
    /* predictor 3: each row's bytes summed straight through, then sample
     * c's bytes are row[c], row[c + w], ... most significant first, a
     * big-endian float whatever the file's byte order (libtiff fpAcc) */
    var planes = floating ? new Uint8Array(rowBytes) : null;
    var planeView = planes ? new DataView(planes.buffer) : view;
    var code = layout.sampleFormat * 100 + layout.bits, bw = layout.blockWidth;
    var r, c, b, p, k = 0, i, end;
    for (r = r0; r < r1; r++, k += cols) {
      p = (r - r0) * rowBytes;
      if (planes) {
        for (i = p + 1, end = p + rowBytes; i < end; i++) data[i] = (data[i] + data[i - 1]) & 255;
        for (b = 0; b < size; b++) {
          for (c = 0; c < cols; c++) planes[c * size + b] = data[p + b * bw + c];
        }
        if (size === 4) {
          for (c = 0; c < cols; c++) values[k + c] = planeView.getFloat32(4 * c, false);
        } else {
          for (c = 0; c < cols; c++) values[k + c] = planeView.getFloat64(8 * c, false);
        }
        continue;
      }
      switch (code) {
        case 108: for (c = 0; c < cols; c++) values[k + c] = data[p + c]; break;
        case 208: for (c = 0; c < cols; c++) values[k + c] = view.getInt8(p + c); break;
        case 116: for (c = 0; c < cols; c++) values[k + c] = view.getUint16(p + 2 * c, little); break;
        case 216: for (c = 0; c < cols; c++) values[k + c] = view.getInt16(p + 2 * c, little); break;
        case 132: for (c = 0; c < cols; c++) values[k + c] = view.getUint32(p + 4 * c, little); break;
        case 232: for (c = 0; c < cols; c++) values[k + c] = view.getInt32(p + 4 * c, little); break;
        case 332: for (c = 0; c < cols; c++) values[k + c] = view.getFloat32(p + 4 * c, little); break;
        default: for (c = 0; c < cols; c++) values[k + c] = view.getFloat64(p + 8 * c, little);
      }
    }
    /* the native value is compared with the no-data value before anything
     * else is done to it; -0 matches 0, in both engines. NaN and Infinity
     * are held in locals: read as globals once a sample, in a Node vm they
     * cost several times the rest of the loop. */
    var nodata = layout.nodata, hasNodata = nodata !== null && nodata !== undefined;
    var judged = !!bounds, low = bounds ? bounds[0] : 0, high = bounds ? bounds[1] : 0;
    var nan = NaN, inf = Infinity, value;
    for (i = 0; i < n; i++) {
      value = values[i];
      if (value !== value || (hasNodata && value === nodata)) {
        values[i] = nan;
        reasons[i] = 1;
      } else if (judged && (value === inf || value === -inf || value < low || value > high)) {
        values[i] = nan;
        reasons[i] = 2;
      } else {
        values[i] = value + 0;
      }
    }
    return { values: values, reasons: reasons, rows: r1 - r0, cols: cols };
  }

  /** A whole GeoTIFF read through the raw layer, as geotiff.read_geotiff
   * reads one: z row-major and south first (rows ascending in latitude or
   * northing), x the column centres ascending and y the row centres
   * ascending, each written as start + index * step from the layout's
   * centres, so both engines give the same bits. Voids (no data,
   * NaN, sparse blocks) are NaN; nothing is judged implausible here. The
   * apps read windows instead; this is for files known to be small, and
   * for tests.
   * @param {Uint8Array} bytes the whole file
   * @param {string} name the file's name, as the sentences give it
   * @returns {{z: Float64Array, x: Float64Array, y: Float64Array, rows: number, cols: number,
   *   layout: TiffLayout}}
   */
  function readGeoTiff(bytes, name) {
    var layout = geotiffLayout(name, bytes.length, [[0, bytes]]);
    if (Array.isArray(layout)) throw new Error('readGeoTiff: bytes are missing from a whole file');
    var width = layout.width, height = layout.height, i, r;
    var z = new Float64Array(width * height);
    blockRanges(layout, 0, height, 0, width).forEach(function (range) {
      var box = tiffBlockBox(layout, range[0]);
      var block = decodeTiffBlock(layout, range[0], bytes.subarray(range[1], range[1] + range[2]),
        range[3], null);
      for (var j = 0; j < block.rows; j++) {
        z.set(block.values.subarray(j * block.cols, (j + 1) * block.cols),
          (height - 1 - (box.top + j)) * width + box.left);
      }
    });
    var x = new Float64Array(width), y = new Float64Array(height);
    for (i = 0; i < width; i++) x[i] = layout.x0 + i * layout.sx;
    for (r = 0; r < height; r++) y[r] = layout.y0 - (height - 1 - r) * layout.sy;
    return { z: z, x: x, y: y, rows: height, cols: width, layout: layout };
  }

  Object.assign(C, {
    geotiffLayout: geotiffLayout, blockRanges: blockRanges, decodeTiffBlock: decodeTiffBlock,
    readGeoTiff: readGeoTiff,
  });

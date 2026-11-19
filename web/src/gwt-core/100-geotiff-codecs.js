
  /* ================================================================ codecs
   * groundwater/geotiff.py's _inflate_block, _lzw_decode and
   * _packbits_decode: DEFLATE (Copernicus GLO-30 tiles, FABDEM), LZW (what
   * GDAL's COG driver and QGIS write by default) and PackBits (QGIS's "low
   * compression"). Written out, beside sha256Hex and for a like reason:
   * DecompressionStream answers only asynchronously, the worker's tasks are
   * synchronous, and the Node sandboxes the tests run in have none. Each
   * takes and returns Uint8Arrays only, and a block that does not decode
   * throws an Error whose code is 'damaged', or 'old_lzw' for the pre-1992
   * form of LZW, which the reader turns into its sentence. */

  /** @typedef {{count: Uint16Array, symbol: Uint16Array, fast: Int32Array}} HuffmanCode */

  /** @param {string} code 'damaged' or 'old_lzw'
   * @returns {Error}
   */
  function codecError(code) {
    var error = /** @type {Error & {code: string}} */ (new Error('the block does not decode: ' + code));
    error.code = code;
    return error;
  }

  var INFLATE_LBASE = [3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31,
    35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258];
  var INFLATE_LEXT = [0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2,
    3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0];
  var INFLATE_DBASE = [1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193,
    257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577];
  var INFLATE_DEXT = [0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6,
    7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13];
  /* the order a dynamic block sends its code-length code's lengths in */
  var INFLATE_ORDER = [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15];
  /* codes this long or shorter are looked up whole; longer ones, which are
   * rare, are walked a bit at a time */
  var INFLATE_FAST = 9;
  /** @type {HuffmanCode[]|null} */
  var inflateFixed = null;

  /* One canonical Huffman code from its code lengths, refused where zlib's
   * inftrees.c refuses it, so the two inflates agree on every stream: an
   * over-subscribed set always; an incomplete one unless it is a single
   * one-bit code, and never for the code-length code. A set with no codes at
   * all is kept and fails only when a symbol is read from it, which is
   * zlib's rule for a block that copies nothing and so sends no distances.
   * (zlib also keeps an empty code-length code, but every stream that has
   * one is refused later, for want of an end-of-block code.) */
  function huffmanCode(lengths, start, n, lengthsCode) {
    var count = new Uint16Array(16), offsets = new Uint16Array(16);
    var symbol = new Uint16Array(n), fast = new Int32Array(1 << INFLATE_FAST).fill(-1);
    var i, len, max = 15, left = 1, code = 0, k = 0;
    for (i = 0; i < n; i++) count[lengths[start + i]]++;
    count[0] = 0;
    while (max > 0 && count[max] === 0) max--;
    for (len = 1; len <= 15; len++) {
      left = (left << 1) - count[len];
      if (left < 0) throw codecError('damaged');
    }
    if (max === 0) {
      if (lengthsCode) throw codecError('damaged');
      return { count: count, symbol: symbol, fast: fast };
    }
    if (left > 0 && (lengthsCode || max !== 1)) throw codecError('damaged');
    for (len = 1; len < 15; len++) offsets[len + 1] = offsets[len] + count[len];
    for (i = 0; i < n; i++) {
      len = lengths[start + i];
      if (len) symbol[offsets[len]++] = i;
    }
    /* each short code, bit-reversed as it arrives, entered at every index
     * whose low bits it fills */
    for (len = 1; len <= INFLATE_FAST; len++) {
      for (i = 0; i < count[len]; i++, k++, code++) {
        var reversed = 0;
        for (var b = 0; b < len; b++) reversed |= ((code >> b) & 1) << (len - 1 - b);
        for (var at = reversed; at < (1 << INFLATE_FAST); at += 1 << len) {
          fast[at] = (len << 16) | symbol[k];
        }
      }
      code <<= 1;
    }
    return { count: count, symbol: symbol, fast: fast };
  }

  /* The fixed codes, complete: literal/lengths 286 and 287 and distances 30
   * and 31 have codes, and reading one is refused where it is read. */
  function inflateFixedCodes() {
    if (!inflateFixed) {
      var lengths = new Uint8Array(288 + 32);
      lengths.fill(8, 0, 144);
      lengths.fill(9, 144, 256);
      lengths.fill(7, 256, 280);
      lengths.fill(8, 280, 288);
      lengths.fill(5, 288, 320);
      inflateFixed = [huffmanCode(lengths, 0, 288, false), huffmanCode(lengths, 288, 32, false)];
    }
    return inflateFixed;
  }

  /** The first `expected` bytes of a zlib-wrapped DEFLATE block, as
   * geotiff._inflate_block gives them. The block is accepted only when the
   * whole stream is valid to its end, Adler-32 included, and holds between
   * `expected` bytes and one `full` block: the rule zlib can be held to
   * whatever it does inside a stream that runs on past what was asked for.
   * Validity is zlib's, check by check (inflate.c and inftrees.c), not the
   * looser one most small inflates apply. The output is allocated at `full`
   * bytes and the byte after that is refused, so a stream that would
   * inflate to gigabytes stops there. Bytes after the checksum are ignored.
   * @param {Uint8Array} bytes the block as stored
   * @param {number} expected the bytes the block has to give
   * @param {number} full the bytes in one full block, the most it may give
   * @returns {Uint8Array}
   */
  function inflateZlib(bytes, expected, full) {
    var src = bytes, size = src.length;
    if (size < 2) throw codecError('damaged');
    var cmf = src[0], flg = src[1];
    /* deflate, a window of 32 KB or less, the header check, no preset
     * dictionary. A smaller declared window is read as 32 KB, as zlib reads
     * it: its own encoder never reaches past what it declared. */
    if ((cmf & 15) !== 8 || (cmf >> 4) > 7 || ((cmf << 8) | flg) % 31 !== 0 || (flg & 32)) {
      throw codecError('damaged');
    }
    var run = inflateRun(src, 2, full);
    var out = run.out, op = run.size, pos = run.end, i, end;
    /* the Adler-32, after the stream */
    if (pos + 4 > size) throw codecError('damaged');
    var a = 1, b = 0;
    for (i = 0; i < op;) {
      for (end = Math.min(op, i + 5552); i < end; i++) {
        a += out[i];
        b += a;
      }
      a %= 65521;
      b %= 65521;
    }
    var check = ((src[pos] << 24) | (src[pos + 1] << 16) | (src[pos + 2] << 8) | src[pos + 3]) >>> 0;
    if ((((b << 16) | a) >>> 0) !== check || op < expected) throw codecError('damaged');
    return expected === full ? out : out.slice(0, expected);
  }

  /** A raw DEFLATE stream, as a ZIP package stores an entry: exactly `size`
   * bytes, by zlib's rules (inflateRun), with nothing in `bytes` after the
   * stream's last block. groundwater/verification.py read_package holds
   * zlib to the same. */
  function inflateRaw(bytes, size) {
    var run = inflateRun(bytes, 0, size);
    if (run.size !== size || run.end !== bytes.length) throw codecError('damaged');
    return run.out;
  }

  /* The DEFLATE blocks of src from byte `pos` to the end of its last block,
   * into at most `full` bytes: {out, size, end}, `end` the byte after the
   * stream's last, whose unused high bits are padding. */
  function inflateRun(src, start, full) {
    var size = src.length;
    var out = new Uint8Array(full);
    var op = 0, pos = start, bitbuf = 0, bitcnt = 0;
    var last, type, lit, dist, codes, len, sym, extra, from, end, i;
    var lengths = new Uint8Array(19), all, nlen, ndist, ncode, repeat, value;

    /* n bits, least significant first; running out of input is damage */
    function bits(n) {
      while (bitcnt < n) {
        if (pos >= size) throw codecError('damaged');
        bitbuf |= src[pos++] << bitcnt;
        bitcnt += 8;
      }
      var v = bitbuf & ((1 << n) - 1);
      bitbuf >>>= n;
      bitcnt -= n;
      return v;
    }

    /* one symbol: a short code at one look, a long one bit by bit */
    function decode(code) {
      while (bitcnt < INFLATE_FAST && pos < size) {
        bitbuf |= src[pos++] << bitcnt;
        bitcnt += 8;
      }
      var hit = code.fast[bitbuf & ((1 << INFLATE_FAST) - 1)];
      if (hit >= 0 && (hit >>> 16) <= bitcnt) {
        bitbuf >>>= hit >>> 16;
        bitcnt -= hit >>> 16;
        return hit & 0xffff;
      }
      var c = 0, first = 0, index = 0;
      for (var l = 1; l <= 15; l++) {
        c |= bits(1);
        var count = code.count[l];
        if (c - count < first) return code.symbol[index + (c - first)];
        index += count;
        first = (first + count) << 1;
        c <<= 1;
      }
      throw codecError('damaged');
    }

    do {
      last = bits(1);
      type = bits(2);
      if (type === 0) {
        /* to a byte boundary: whole bytes already in the bit buffer go
         * back, and the rest of the byte the header came from is dropped */
        pos -= bitcnt >> 3;
        bitbuf = 0;
        bitcnt = 0;
        if (pos + 4 > size) throw codecError('damaged');
        len = src[pos] | (src[pos + 1] << 8);
        if (len !== (~(src[pos + 2] | (src[pos + 3] << 8)) & 0xffff)) throw codecError('damaged');
        pos += 4;
        if (pos + len > size || op + len > full) throw codecError('damaged');
        out.set(src.subarray(pos, pos + len), op);
        op += len;
        pos += len;
        continue;
      }
      if (type === 1) {
        codes = inflateFixedCodes();
        lit = codes[0];
        dist = codes[1];
      } else if (type === 2) {
        nlen = bits(5) + 257;
        ndist = bits(5) + 1;
        ncode = bits(4) + 4;
        if (nlen > 286 || ndist > 30) throw codecError('damaged');
        lengths.fill(0);
        for (i = 0; i < ncode; i++) lengths[INFLATE_ORDER[i]] = bits(3);
        codes = huffmanCode(lengths, 0, 19, true);
        all = new Uint8Array(nlen + ndist);
        for (i = 0; i < nlen + ndist;) {
          sym = decode(codes);
          if (sym < 16) {
            all[i++] = sym;
            continue;
          }
          value = 0;
          if (sym === 16) {
            if (i === 0) throw codecError('damaged');
            value = all[i - 1];
            repeat = 3 + bits(2);
          } else if (sym === 17) {
            repeat = 3 + bits(3);
          } else {
            repeat = 11 + bits(7);
          }
          if (i + repeat > nlen + ndist) throw codecError('damaged');
          for (end = i + repeat; i < end;) all[i++] = value;
        }
        if (all[256] === 0) throw codecError('damaged');   // no end-of-block code
        lit = huffmanCode(all, 0, nlen, false);
        dist = huffmanCode(all, nlen, ndist, false);
      } else {
        throw codecError('damaged');
      }
      for (;;) {
        sym = decode(lit);
        if (sym < 256) {
          if (op >= full) throw codecError('damaged');
          out[op++] = sym;
        } else if (sym === 256) {
          break;
        } else {
          sym -= 257;
          if (sym >= 29) throw codecError('damaged');
          len = INFLATE_LBASE[sym] + bits(INFLATE_LEXT[sym]);
          sym = decode(dist);
          if (sym >= 30) throw codecError('damaged');
          extra = INFLATE_DBASE[sym] + bits(INFLATE_DEXT[sym]);
          if (extra > op || op + len > full) throw codecError('damaged');
          /* byte by byte, since a copy may overlap what it is writing */
          for (from = op - extra, end = op + len; op < end;) out[op++] = out[from++];
        }
      }
    } while (!last);

    /* the whole bytes still unread in the bit buffer are not the stream's */
    return { out: out, size: op, end: pos - (bitcnt >> 3) };
  }

  /* libtiff's table bound: 4,096 twelve-bit codes plus 1,023 entries no code
   * can name (MAXCODE(12) + 1024, tif_lzw.c). An encoder that defers its
   * Clear may keep adding to the table that far, and libtiff and GDAL read
   * what it wrote. */
  var LZW_TABLE = 5119;

  /** The first `expected` bytes of a TIFF LZW strip or tile, as
   * geotiff._lzw_decode gives them: codes most significant bit first,
   * widening one code early, at 511, 1023 and 2047. Decoding stops once
   * `expected` bytes are out, so whatever follows - an end code or not,
   * padding, codes no valid table could hold - is never looked at; a stream
   * that ends before then, or names a code the table does not hold, is
   * damaged. The table is four arrays, each entry its prefix's code and one
   * byte, and each entry is written straight into the output, last byte
   * first.
   * @param {Uint8Array} bytes the strip or tile as stored
   * @param {number} expected the bytes it has to give
   * @returns {Uint8Array}
   */
  function lzwDecode(bytes, expected) {
    var size = bytes.length;
    /* the pre-1992 form, least significant bit first: libtiff's own test */
    if (size >= 2 && bytes[0] === 0 && (bytes[1] & 1)) throw codecError('old_lzw');
    var data = new Uint8Array(size + 3);
    data.set(bytes);
    var prefix = new Uint16Array(LZW_TABLE), suffix = new Uint8Array(LZW_TABLE);
    var length = new Uint16Array(LZW_TABLE), first = new Uint8Array(LZW_TABLE);
    for (var i = 0; i < 256; i++) {
      suffix[i] = i;
      first[i] = i;
      length[i] = 1;
    }
    var out = new Uint8Array(expected);
    var bits = size * 8, pos = 0, width = 9, next = 258, prev = -1, op = 0;
    var p, code, tail, at, c;
    while (op < expected) {
      if (bits - pos < width) break;   // no end code: stop where the data stops
      p = pos >>> 3;
      code = (((data[p] << 16) | (data[p + 1] << 8) | data[p + 2]) >>> (24 - (pos & 7) - width)) &
        ((1 << width) - 1);
      pos += width;
      if (code === 257) break;
      if (code === 256) {
        next = 258;
        width = 9;
        prev = -1;
        continue;
      }
      if (prev < 0) {
        if (code > 255) throw codecError('damaged');
        out[op++] = code;
        prev = code;
        continue;
      }
      if (code < next) tail = first[code];
      else if (code === next) tail = first[prev];
      else throw codecError('damaged');
      if (next === LZW_TABLE) throw codecError('damaged');
      prefix[next] = prev;
      suffix[next] = tail;
      length[next] = length[prev] + 1;
      first[next] = first[prev];
      next++;
      if (next + 1 >= (1 << width) && width < 12) width++;
      /* backwards from the entry's last byte, past what falls beyond the block */
      c = code;
      for (at = op + length[code] - 1; at >= expected; at--) c = prefix[c];
      for (; at >= op; at--) {
        out[at] = suffix[c];
        c = prefix[c];
      }
      op += length[code];
      prev = code;
    }
    if (op < expected) throw codecError('damaged');
    return out;
  }

  /** The first `expected` bytes of a PackBits strip or tile, as
   * geotiff._packbits_decode gives them. Each header byte n, read as signed,
   * is followed by n + 1 bytes to copy (0 to 127), one byte to repeat 1 - n
   * times (-127 to -1), or nothing (-128). A run reaching past `expected` is
   * cut there and needs only the bytes it uses, as libtiff reads it;
   * running out of data first is damage.
   * @param {Uint8Array} bytes the strip or tile as stored
   * @param {number} expected the bytes it has to give
   * @returns {Uint8Array}
   */
  function packbitsDecode(bytes, expected) {
    var out = new Uint8Array(expected), size = bytes.length, pos = 0, op = 0;
    var header, take;
    while (op < expected) {
      if (pos >= size) throw codecError('damaged');
      header = bytes[pos++];
      if (header < 128) {
        take = Math.min(header + 1, expected - op);
        if (pos + take > size) throw codecError('damaged');
        out.set(bytes.subarray(pos, pos + take), op);
        op += take;
        pos += header + 1;
      } else if (header > 128) {
        if (pos >= size) throw codecError('damaged');
        take = Math.min(257 - header, expected - op);
        out.fill(bytes[pos++], op, op + take);
        op += take;
      }
    }
    return out;
  }

  Object.assign(C, {
    inflateZlib: inflateZlib, lzwDecode: lzwDecode, packbitsDecode: packbitsDecode,
  });

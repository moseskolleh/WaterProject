

  /* ===================================================================
   * QR symbols - a port of groundwater/qr.py
   *
   * The identifier on a headworks plate is only useful if the phone in the
   * technician's pocket reads it, and the places this runs have no signal to
   * fetch an image over. So the symbol is generated here, offline, from no
   * dependency: byte mode, versions 1 to 10, all four error-correction
   * levels. The Python side is held to an independent encoder and to a real
   * decoder; this side is held to the Python side, module for module.
   * =================================================================== */

  var QR_ECC_LEVELS = { L: 0.07, M: 0.15, Q: 0.25, H: 0.30 };
  var QR_MAX_VERSION = 10;
  var QR_ECC_BITS = { L: 1, M: 0, Q: 3, H: 2 };

  /* (ec codewords per block, g1 blocks, g1 data, g2 blocks, g2 data) */
  var QR_BLOCKS = {
    1: { L: [7, 1, 19, 0, 0], M: [10, 1, 16, 0, 0], Q: [13, 1, 13, 0, 0], H: [17, 1, 9, 0, 0] },
    2: { L: [10, 1, 34, 0, 0], M: [16, 1, 28, 0, 0], Q: [22, 1, 22, 0, 0], H: [28, 1, 16, 0, 0] },
    3: { L: [15, 1, 55, 0, 0], M: [26, 1, 44, 0, 0], Q: [18, 2, 17, 0, 0], H: [22, 2, 13, 0, 0] },
    4: { L: [20, 1, 80, 0, 0], M: [18, 2, 32, 0, 0], Q: [26, 2, 24, 0, 0], H: [16, 4, 9, 0, 0] },
    5: { L: [26, 1, 108, 0, 0], M: [24, 2, 43, 0, 0], Q: [18, 2, 15, 2, 16], H: [22, 2, 11, 2, 12] },
    6: { L: [18, 2, 68, 0, 0], M: [16, 4, 27, 0, 0], Q: [24, 4, 19, 0, 0], H: [28, 4, 15, 0, 0] },
    7: { L: [20, 2, 78, 0, 0], M: [18, 4, 31, 0, 0], Q: [18, 2, 14, 4, 15], H: [26, 4, 13, 1, 14] },
    8: { L: [24, 2, 97, 0, 0], M: [22, 2, 38, 2, 39], Q: [22, 4, 18, 2, 19], H: [26, 4, 14, 2, 15] },
    9: { L: [30, 2, 116, 0, 0], M: [22, 3, 36, 2, 37], Q: [20, 4, 16, 4, 17], H: [24, 4, 12, 4, 13] },
    10: { L: [18, 2, 68, 2, 69], M: [26, 4, 43, 1, 44], Q: [24, 6, 19, 2, 20], H: [28, 6, 15, 2, 16] }
  };

  var QR_ALIGNMENT = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34],
    7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50]
  };
  var QR_VERSION_INFO = { 7: 0x07C94, 8: 0x085BC, 9: 0x09A99, 10: 0x0A4D3 };
  var QR_REMAINDER_BITS = { 1: 0, 2: 7, 3: 7, 4: 7, 5: 7, 6: 7, 7: 0, 8: 0, 9: 0, 10: 0 };

  var QR_EXP = new Array(512), QR_LOG = new Array(256);
  (function buildGaloisTables() {
    var x = 1;
    for (var i = 0; i < 255; i++) {
      QR_EXP[i] = x;
      QR_LOG[x] = i;
      x <<= 1;
      if (x & 0x100) x ^= 0x11D;
    }
    for (var j = 255; j < 512; j++) QR_EXP[j] = QR_EXP[j - 255];
  }());

  function gfMul(a, b) {
    if (a === 0 || b === 0) return 0;
    return QR_EXP[QR_LOG[a] + QR_LOG[b]];
  }

  function qrGeneratorPoly(degree) {
    var poly = [1];
    for (var i = 0; i < degree; i++) {
      var next = new Array(poly.length + 1).fill(0);
      for (var j = 0; j < poly.length; j++) {
        next[j] ^= gfMul(poly[j], 1);
        next[j + 1] ^= gfMul(poly[j], QR_EXP[i]);
      }
      poly = next;
    }
    return poly;
  }

  function qrEcCodewords(data, count) {
    var gen = qrGeneratorPoly(count);
    var remainder = data.concat(new Array(count).fill(0));
    for (var i = 0; i < data.length; i++) {
      var lead = remainder[i];
      if (!lead) continue;
      for (var j = 0; j < gen.length; j++) {
        remainder[i + j] ^= gfMul(gen[j], lead);
      }
    }
    return remainder.slice(data.length);
  }

  /**
   * @param {number} version 1 to 40
   * @param {string} ecc 'L', 'M', 'Q' or 'H'
   * @returns {number}
   */
  function qrCapacityBytes(version, ecc) {
    var b = QR_BLOCKS[version][ecc];
    var dataCodewords = b[1] * b[2] + b[3] * b[4];
    var countBits = version < 10 ? 8 : 16;
    return Math.floor((dataCodewords * 8 - 4 - countBits) / 8);
  }

  function qrChooseVersion(length, ecc, minVersion) {
    for (var v = Math.max(1, minVersion || 1); v <= QR_MAX_VERSION; v++) {
      if (length <= qrCapacityBytes(v, ecc)) return v;
    }
    throw new Error(length + ' bytes will not fit in a version-' + QR_MAX_VERSION +
      ' symbol at error-correction level ' + ecc + '; shorten the payload');
  }

  function qrBitstream(payload, version, ecc) {
    var b = QR_BLOCKS[version][ecc];
    var capacityBits = (b[1] * b[2] + b[3] * b[4]) * 8;
    var bits = [0, 1, 0, 0];
    var countBits = version < 10 ? 8 : 16, shift;
    for (shift = countBits - 1; shift >= 0; shift--) bits.push((payload.length >> shift) & 1);
    for (var i = 0; i < payload.length; i++) {
      for (shift = 7; shift >= 0; shift--) bits.push((payload[i] >> shift) & 1);
    }
    var terminator = Math.min(4, capacityBits - bits.length);
    for (var t = 0; t < terminator; t++) bits.push(0);
    while (bits.length % 8) bits.push(0);
    var pad = [0xEC, 0x11], k = 0;
    while (bits.length < capacityBits) {
      for (shift = 7; shift >= 0; shift--) bits.push((pad[k % 2] >> shift) & 1);
      k++;
    }
    return bits;
  }

  function qrInterleave(bits, version, ecc) {
    var spec = QR_BLOCKS[version][ecc], ecPerBlock = spec[0];
    var codewords = [];
    for (var i = 0; i < bits.length; i += 8) {
      var value = 0;
      for (var s = 0; s < 8; s++) value = (value << 1) | bits[i + s];
      codewords.push(value);
    }
    var blocks = [], at = 0;
    [[spec[1], spec[2]], [spec[3], spec[4]]].forEach(function (group) {
      for (var n = 0; n < group[0]; n++) {
        blocks.push(codewords.slice(at, at + group[1]));
        at += group[1];
      }
    });
    var ecBlocks = blocks.map(function (block) { return qrEcCodewords(block, ecPerBlock); });

    var longest = Math.max.apply(null, blocks.map(function (b2) { return b2.length; }));
    var out = [], j;
    for (i = 0; i < longest; i++) {
      for (j = 0; j < blocks.length; j++) {
        if (i < blocks[j].length) out.push(blocks[j][i]);
      }
    }
    for (i = 0; i < ecPerBlock; i++) {
      for (j = 0; j < ecBlocks.length; j++) out.push(ecBlocks[j][i]);
    }
    var final = [];
    out.forEach(function (codeword) {
      for (var shift = 7; shift >= 0; shift--) final.push((codeword >> shift) & 1);
    });
    for (i = 0; i < QR_REMAINDER_BITS[version]; i++) final.push(0);
    return final;
  }

  function qrGrid(size) {
    var grid = [];
    for (var i = 0; i < size; i++) grid.push(new Array(size).fill(false));
    return grid;
  }

  function qrPlaceFunctionPatterns(modules, reserved, version) {
    var size = modules.length, i, r, c;

    function finder(row, col) {
      for (r = -1; r < 8; r++) {
        for (c = -1; c < 8; c++) {
          var rr = row + r, cc = col + c;
          if (rr < 0 || rr >= size || cc < 0 || cc >= size) continue;
          var edge = Math.max(Math.abs(r - 3), Math.abs(c - 3));
          modules[rr][cc] = edge !== 2 && edge <= 3;
          reserved[rr][cc] = true;
        }
      }
    }
    finder(0, 0);
    finder(0, size - 7);
    finder(size - 7, 0);

    for (i = 0; i < size; i++) {
      if (!reserved[6][i]) { modules[6][i] = i % 2 === 0; reserved[6][i] = true; }
      if (!reserved[i][6]) { modules[i][6] = i % 2 === 0; reserved[i][6] = true; }
    }

    /* Every combination of the centres but the three corners the finders
     * hold. Tested on the index, not on whether the cell is taken: from
     * version 7 the first centre is 6, so those patterns lie across the
     * timing lines and are drawn over them. */
    var centres = QR_ALIGNMENT[version], last = centres.length - 1;
    centres.forEach(function (row, a) {
      centres.forEach(function (col, b) {
        if ((a === 0 && b === 0) || (a === 0 && b === last) || (a === last && b === 0)) return;
        for (var dr = -2; dr < 3; dr++) {
          for (var dc = -2; dc < 3; dc++) {
            modules[row + dr][col + dc] = Math.max(Math.abs(dr), Math.abs(dc)) !== 1;
            reserved[row + dr][col + dc] = true;
          }
        }
      });
    });

    modules[4 * version + 9][8] = true;
    reserved[4 * version + 9][8] = true;

    for (i = 0; i < 9; i++) { reserved[8][i] = true; reserved[i][8] = true; }
    for (i = 0; i < 8; i++) {
      reserved[8][size - 1 - i] = true;
      reserved[size - 1 - i][8] = true;
    }

    if (version >= 7) {
      var info = QR_VERSION_INFO[version];
      for (i = 0; i < 18; i++) {
        var bit = ((info >> i) & 1) === 1;
        var row2 = Math.floor(i / 3), col2 = size - 11 + (i % 3);
        modules[row2][col2] = bit;
        reserved[row2][col2] = true;
        modules[col2][row2] = bit;
        reserved[col2][row2] = true;
      }
    }
  }

  function qrPlaceData(modules, reserved, bits) {
    var size = modules.length, at = 0, upward = true, col = size - 1;
    while (col > 0) {
      if (col === 6) col -= 1;
      for (var n = 0; n < size; n++) {
        var row = upward ? size - 1 - n : n;
        for (var k = 0; k < 2; k++) {
          var c = col - k;
          if (reserved[row][c]) continue;
          modules[row][c] = at < bits.length && bits[at] === 1;
          at += 1;
        }
      }
      upward = !upward;
      col -= 2;
    }
  }

  var QR_MASKS = [
    function (i, j) { return (i + j) % 2 === 0; },
    function (i) { return i % 2 === 0; },
    function (i, j) { return j % 3 === 0; },
    function (i, j) { return (i + j) % 3 === 0; },
    function (i, j) { return (Math.floor(i / 2) + Math.floor(j / 3)) % 2 === 0; },
    function (i, j) { return (i * j) % 2 + (i * j) % 3 === 0; },
    function (i, j) { return ((i * j) % 2 + (i * j) % 3) % 2 === 0; },
    function (i, j) { return ((i + j) % 2 + (i * j) % 3) % 2 === 0; }
  ];

  function qrApplyMask(modules, reserved, mask) {
    var rule = QR_MASKS[mask];
    return modules.map(function (row, i) {
      return row.map(function (cell, j) {
        return !reserved[i][j] && rule(i, j) ? !cell : cell;
      });
    });
  }

  function qrFormatBits(ecc, mask) {
    var value = (QR_ECC_BITS[ecc] << 3) | mask;
    var remainder = value;
    for (var i = 0; i < 10; i++) {
      remainder = (remainder << 1) ^ ((remainder >> 9) * 0x537);
    }
    return ((value << 10) | remainder) ^ 0x5412;
  }

  function qrPlaceFormat(modules, ecc, mask) {
    var size = modules.length, bits = qrFormatBits(ecc, mask), i;
    function bit(n) { return ((bits >> n) & 1) === 1; }

    for (i = 0; i < 6; i++) modules[i][8] = bit(i);
    modules[7][8] = bit(6);
    modules[8][8] = bit(7);
    modules[8][7] = bit(8);
    for (i = 9; i < 15; i++) modules[8][14 - i] = bit(i);

    for (i = 0; i < 8; i++) modules[8][size - 1 - i] = bit(i);
    for (i = 8; i < 15; i++) modules[size - 15 + i][8] = bit(i);
    modules[size - 8][8] = true;
  }

  var QR_PENALTY_RUN = 3, QR_PENALTY_BLOCK = 3, QR_PENALTY_FINDER = 40,
    QR_PENALTY_BALANCE = 10;

  function qrFinderLike(history) {
    var unit = history[1];
    var core = unit > 0 && history[2] === unit && history[3] === unit * 3 &&
      history[4] === unit && history[5] === unit;
    return (core && history[0] >= unit * 4 && history[6] >= unit ? 1 : 0) +
      (core && history[6] >= unit * 4 && history[0] >= unit ? 1 : 0);
  }

  /**
   * @param {boolean[][]} modules
   * @returns {number}
   */
  function qrPenalty(modules) {
    var size = modules.length, score = 0, i, j;
    var lines = modules.map(function (row) { return row.slice(); });
    for (j = 0; j < size; j++) {
      var column = [];
      for (i = 0; i < size; i++) column.push(modules[i][j]);
      lines.push(column);
    }
    lines.forEach(function (line) {
      var colour = false, run = 0, history = new Array(7).fill(0);
      function remember(length) {
        if (history[0] === 0) length += size;
        history.pop();
        history.unshift(length);
      }
      line.forEach(function (cell) {
        if (cell === colour) {
          run += 1;
          if (run === 5) score += QR_PENALTY_RUN;
          else if (run > 5) score += 1;
        } else {
          remember(run);
          if (!colour) score += qrFinderLike(history) * QR_PENALTY_FINDER;
          colour = cell;
          run = 1;
        }
      });
      if (colour) { remember(run); run = 0; }
      remember(run + size);
      score += qrFinderLike(history) * QR_PENALTY_FINDER;
    });
    for (i = 0; i < size - 1; i++) {
      for (j = 0; j < size - 1; j++) {
        var a = modules[i][j], b = modules[i][j + 1],
          c = modules[i + 1][j], d = modules[i + 1][j + 1];
        if ((a && b && c && d) || (!a && !b && !c && !d)) score += QR_PENALTY_BLOCK;
      }
    }
    var dark = 0;
    modules.forEach(function (row) {
      row.forEach(function (cell) { if (cell) dark += 1; });
    });
    var total = size * size;
    var k = Math.ceil(Math.abs(dark * 20 - total * 10) / total) - 1;
    return score + Math.max(k, 0) * QR_PENALTY_BALANCE;
  }

  function utf8Bytes(text) {
    var out = [];
    for (var i = 0; i < text.length; i++) {
      var code = text.charCodeAt(i);
      if (code < 0x80) { out.push(code); continue; }
      if (code < 0x800) {
        out.push(0xC0 | (code >> 6), 0x80 | (code & 63));
        continue;
      }
      if (code >= 0xD800 && code <= 0xDBFF && i + 1 < text.length) {
        var low = text.charCodeAt(i + 1);
        if (low >= 0xDC00 && low <= 0xDFFF) {
          code = 0x10000 + ((code - 0xD800) << 10) + (low - 0xDC00);
          i += 1;
          out.push(0xF0 | (code >> 18), 0x80 | ((code >> 12) & 63),
            0x80 | ((code >> 6) & 63), 0x80 | (code & 63));
          continue;
        }
      }
      out.push(0xE0 | (code >> 12), 0x80 | ((code >> 6) & 63), 0x80 | (code & 63));
    }
    return out;
  }

  /** options: {ecc, minVersion, mask}
   * @param {string} text
   * @param {Rec} [options] ecc, minVersion, mask
   */
  function qrEncode(text, options) {
    var opts = options || {};
    var ecc = opts.ecc || 'H';
    if (!own(QR_ECC_LEVELS, ecc)) {
      throw new Error("unknown error-correction level '" + ecc + "'");
    }
    var mask = opts.mask === undefined || opts.mask === null ? null : opts.mask;
    if (mask !== null && !(mask >= 0 && mask <= 7)) {
      throw new Error('mask must be 0 to 7, not ' + mask);
    }
    var payload = utf8Bytes(String(text));
    var version = qrChooseVersion(payload.length, ecc, opts.minVersion || 1);
    var bits = qrInterleave(qrBitstream(payload, version, ecc), version, ecc);
    var size = 17 + 4 * version;
    var modules = qrGrid(size), reserved = qrGrid(size);
    qrPlaceFunctionPatterns(modules, reserved, version);
    qrPlaceData(modules, reserved, bits);

    var best = null, bestMask = 0, bestScore = null;
    var candidates = mask === null ? [0, 1, 2, 3, 4, 5, 6, 7] : [mask];
    candidates.forEach(function (candidateMask) {
      var candidate = qrApplyMask(modules, reserved, candidateMask);
      qrPlaceFormat(candidate, ecc, candidateMask);
      var score = qrPenalty(candidate);
      if (bestScore === null || score < bestScore) {
        best = candidate; bestMask = candidateMask; bestScore = score;
      }
    });
    return { version: version, ecc: ecc, mask: bestMask, size: size, modules: best };
  }

  /** The symbol as an SVG string. The quiet zone is not decoration: a symbol
   * printed hard against a frame is much harder for a phone to find.
   * @param {{size: number, modules: boolean[][]}} code what qrEncode returns
   * @param {Rec} [options] scale, border
   * @returns {string}
   */
  function qrSvg(code, options) {
    var opts = options || {};
    var scale = opts.scale || 4, border = opts.border === undefined ? 4 : opts.border;
    var size = code.size + 2 * border, parts = [];
    for (var row = 0; row < code.size; row++) {
      for (var col = 0; col < code.size; col++) {
        if (code.modules[row][col]) {
          parts.push('M' + (col + border) + ' ' + (row + border) + 'h1v1h-1z');
        }
      }
    }
    return '<svg xmlns="http://www.w3.org/2000/svg" width="' + (size * scale) +
      '" height="' + (size * scale) + '" viewBox="0 0 ' + size + ' ' + size +
      '" shape-rendering="crispEdges">' +
      '<rect width="' + size + '" height="' + size + '" fill="#ffffff"/>' +
      '<path fill="#000000" d="' + parts.join('') + '"/></svg>';
  }

  function pngChunk(kind, payload) {
    var out = new Uint8Array(12 + payload.length);
    var view = new DataView(out.buffer);
    view.setUint32(0, payload.length);
    for (var i = 0; i < 4; i++) out[4 + i] = kind.charCodeAt(i);
    out.set(payload, 8);
    view.setUint32(8 + payload.length, crc32Of(out.subarray(4, 8 + payload.length)));
    return out;
  }

  /** The symbol as a greyscale PNG, as qr.to_png(stored=True) draws it, byte
   * for byte, with no canvas: the cover of a document the worker or a test
   * writes has none. Its pixel data is stored in a zlib stream without
   * compression, so the bytes are the same in every browser and in Python;
   * the package it goes into compresses them.
   * @param {{size: number, modules: boolean[][]}} code what qrEncode returns
   * @param {Rec} [options] scale, border
   * @returns {Uint8Array}
   */
  function qrPng(code, options) {
    var opts = options || {};
    var scale = opts.scale || 8, border = opts.border === undefined ? 4 : opts.border;
    var size = (code.size + 2 * border) * scale, stride = size + 1;
    var raw = new Uint8Array(size * stride);
    for (var y = 0; y < size; y++) {
      var row = Math.floor(y / scale) - border;
      for (var x = 0; x < size; x++) {
        var col = Math.floor(x / scale) - border;
        var dark = row >= 0 && row < code.size && col >= 0 && col < code.size && code.modules[row][col];
        raw[y * stride + 1 + x] = dark ? 0 : 255;
      }
    }
    var blocks = Math.max(1, Math.ceil(raw.length / 65535));
    var zlib = new Uint8Array(2 + raw.length + 5 * blocks + 4);
    zlib[0] = 0x78;
    zlib[1] = 0x01;
    var at = 2;
    for (var b = 0; b < blocks; b++) {
      var from = b * 65535, len = Math.min(65535, raw.length - from);
      zlib[at] = b === blocks - 1 ? 1 : 0;
      zlib[at + 1] = len & 255;
      zlib[at + 2] = len >> 8;
      zlib[at + 3] = ~len & 255;
      zlib[at + 4] = (~len >> 8) & 255;
      zlib.set(raw.subarray(from, from + len), at + 5);
      at += 5 + len;
    }
    var a = 1, s = 0;
    for (var i = 0; i < raw.length; i++) {
      a = (a + raw[i]) % 65521;
      s = (s + a) % 65521;
    }
    new DataView(zlib.buffer).setUint32(at, ((s << 16) | a) >>> 0);
    var header = new Uint8Array(13);
    var hv = new DataView(header.buffer);
    hv.setUint32(0, size);
    hv.setUint32(4, size);
    header[8] = 8;   // eight bits a pixel, greyscale, no interlace
    var chunks = [Uint8Array.of(0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a),
      pngChunk('IHDR', header), pngChunk('IDAT', zlib), pngChunk('IEND', new Uint8Array(0))];
    var total = chunks.reduce(function (n, c) { return n + c.length; }, 0);
    var png = new Uint8Array(total), off = 0;
    chunks.forEach(function (c) { png.set(c, off); off += c.length; });
    return png;
  }

  Object.assign(C, {
    QR_ECC_LEVELS: QR_ECC_LEVELS, QR_MAX_VERSION: QR_MAX_VERSION,
    qrEncode: qrEncode, qrSvg: qrSvg, qrPng: qrPng, qrCapacityBytes: qrCapacityBytes,
    qrPenalty: qrPenalty
  });

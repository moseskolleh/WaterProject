
  /* =============================================================== extraction
   * groundwater/extraction/*. Getting a field sheet that arrived as a scan or
   * a PDF into the same records an uploaded template produces.
   *
   * Whatever the source, the result is header fields plus data tables, each
   * value carrying a confidence in [0, 1]. Values below the review threshold
   * are flagged and highlighted amber in the review workbook rather than
   * silently accepted: an extractor that quietly guesses a digit is worse than
   * no extractor at all.
   *
   * Two paths, as on the server. A PDF that carries a text layer is read
   * directly here - the whole reader is below, because the page must not fetch
   * a PDF library from a CDN. A photographed or image-only sheet has no text
   * to read and goes to the Claude API, which needs a key the operator
   * supplies on the Settings page.
   */

  var REVIEW_THRESHOLD = 0.85;

  var KIND_MARKERS = {
    ves: ['ves', 'schlumberger', 'apparent resistivity', 'sounding'],
    pumping_test: ['pumping test', 'step test', 'constant discharge', 'drawdown'],
    drilling_log: ['drilling', 'borehole log', 'penetration'],
    water_quality: ['water quality', 'laboratory', 'parameter', 'guideline'],
  };

  /**
   * @param {*} text
   * @returns {string}
   */
  function guessDocumentKind(text) {
    var lower = String(text || '').toLowerCase();
    var best = 'unknown', bestScore = 0;
    Object.keys(KIND_MARKERS).forEach(function (kind) {
      var score = KIND_MARKERS[kind].filter(function (marker) {
        return lower.indexOf(marker) >= 0;
      }).length;
      if (score > bestScore) { bestScore = score; best = kind; }
    });
    return bestScore > 0 ? best : 'unknown';
  }

  /**
   * @param {string} name
   * @param {*} value
   * @param {number|string} [confidence]
   */
  function extractedField(name, value, confidence) {
    var conf = confidence === undefined ? 1.0 : Number(confidence);
    return {
      name: name, value: value, confidence: conf,
      needs_review: conf < REVIEW_THRESHOLD,
    };
  }

  /**
   * @param {Rec} table an extracted table
   * @param {number} index
   * @returns {number}
   */
  function confidenceForRow(table, index) {
    var list = table.row_confidence || [];
    return index < list.length ? list[index] : 1.0;
  }

  /** The columns of an extracted VES table the template takes, and what it
   * lacks: review.py ves_template_columns. `placed` maps ab2, mn or mn_half,
   * rho or resistance, and k to the table's columns; `missing` holds the
   * extraction.ves_missing keys that keep the readings out of the template.
   * The columns are read by the VES reader's own rules, which are the rules
   * that read the filled template back. Picked by substring instead, a sheet
   * headed AB/2, MN/2, K, Resistance (ohm), App. Resistivity (ohm-m) had its
   * resistances written into the apparent-resistivity column and its
   * half-spacings into the full MN column, with nothing flagged.
   * @param {Rec} table an extracted table
   * @returns {{placed: Record<string, number>, missing: string[]}}
   */
  function vesTemplateColumns(table) {
    var cols = vesReadingColumns(table.columns || []);
    /** @type {Record<string, number>} */
    var placed = {};
    var missing = [];
    if ('ab2' in cols) placed.ab2 = cols.ab2;
    else missing.push('a' in cols ? 'wenner' : 'spacing');
    if ('mn' in cols) placed.mn = cols.mn;
    else if ('mn_half' in cols) placed.mn_half = cols.mn_half;
    if ('rho' in cols) {
      placed.rho = cols.rho;
    } else if ('resistance' in cols) {
      placed.resistance = cols.resistance;
      if ('k' in cols) placed.k = cols.k;
      /* the reader works K out from AB/2 and MN; with neither K nor MN every
       * row would be dropped */
      else if (!('mn' in placed) && !('mn_half' in placed)) missing.push('factor');
    } else {
      missing.push('value');
    }
    return { placed: placed, missing: missing };
  }

  function vesUnplaced(table, missing) {
    var reasons = phraseTable('extraction.ves_missing');
    return phrase('extraction.ves_unplaced', {
      table: String(table.title),
      missing: missing.map(function (key) { return reasons[key]; }).join('; '),
      headings: (table.columns || []).map(function (c) {
        return "'" + c + "'";
      }).join(', ') || 'none',
    });
  }

  /** What needs checking about the sheet as a whole, before any one value:
   * review.py sheet_review_items. A sheet whose table was not found, or a VES
   * sheet whose readings the template cannot take, has lost every reading,
   * and its review used to say "None: all values extracted with high
   * confidence".
   * @param {Rec} document an extracted document
   * @returns {string[]}
   */
  function sheetReviewItems(document) {
    var tables = document.tables || [];
    if (!tables.length) return [phrase('extraction.no_table')];
    if (document.document_kind === 'ves') {
      var missing = vesTemplateColumns(tables[0]).missing;
      if (missing.length) return [vesUnplaced(tables[0], missing)];
    }
    return [];
  }

  /** Everything a human still has to look at, in the words the review sheet
   * uses. Mirrors ExtractedDocument.review_items: the sheet as a whole first,
   * then the header fields and the cells.
   * @param {Rec} document an extracted document
   * @returns {string[]}
   */
  function reviewItems(document) {
    var items = sheetReviewItems(document).concat(
      (document.header || []).filter(function (f) { return f.needs_review; })
        .map(function (f) {
          return "header field '" + f.name + "' = '" + f.value + "' (confidence " +
            pyFixed(f.confidence, 2) + ')';
        }));
    (document.uncertain_cells || []).forEach(function (cell) {
      var table = (document.tables || [])[cell.table_index];
      if (!table) return;
      var value = '';
      var row = table.rows[cell.row];
      if (row && cell.column < row.length) value = row[cell.column];
      var column = cell.column < table.columns.length
        ? table.columns[cell.column] : String(cell.column + 1);
      items.push("table '" + table.title + "' row " + (cell.row + 1) +
        ", column '" + column + "' = '" + value + "'" +
        (cell.reason ? ' (' + cell.reason + ')' : ''));
    });
    return items;
  }

  /* --- the PDF text layer ---------------------------------------------------
   *
   * A deliberately small reader: enough of the PDF grammar to pull the text
   * that a generated field sheet carries, and no more. Objects are found by
   * scanning rather than through the cross-reference table, because a sheet
   * that has been through a scanner-printer often has a broken xref while its
   * objects are perfectly readable.
   */

  /* A /FlateDecode stream is zlib-wrapped, but a few writers emit the raw
   * deflate stream without the two-byte header, so try both rather than
   * failing the whole document. Kept local so this module stays free of the
   * DOM support layer. */
  async function inflateStream(bytes) {
    if (typeof DecompressionStream === 'undefined') {
      throw new Error('This browser cannot decompress PDF streams.');
    }
    /** @type {CompressionFormat[]} */
    var formats = ['deflate', 'deflate-raw'];
    for (var i = 0; i < formats.length; i++) {
      try {
        var stream = new Blob([bytes]).stream()
          .pipeThrough(new DecompressionStream(formats[i]));
        return new Uint8Array(await new Response(stream).arrayBuffer());
      } catch (e) {
        if (i === formats.length - 1) throw e;
      }
    }
    return bytes;
  }

  function latin1(bytes) {
    var out = '', chunk = 0x8000;
    for (var i = 0; i < bytes.length; i += chunk) {
      out += String.fromCharCode.apply(
        null, bytes.subarray(i, Math.min(i + chunk, bytes.length)));
    }
    return out;
  }

  /* /Contents 4 0 R, or /Contents [4 0 R 5 0 R] - both are common. */
  function pdfRefs(dict, key) {
    var re = new RegExp('/' + key + '\\s*(\\[[^\\]]*\\]|\\d+\\s+\\d+\\s+R)');
    var m = re.exec(dict);
    if (!m) return [];
    var refs = [];
    var each = /(\d+)\s+(\d+)\s+R/g, hit;
    while ((hit = each.exec(m[1])) !== null) refs.push(Number(hit[1]));
    return refs;
  }

  /* Balanced << >> starting at `from`, so a nested dictionary is not cut in
   * half by the first >> that happens to come along. */
  function pdfDictAt(text, from) {
    var depth = 0, i = from;
    while (i < text.length) {
      if (text.substr(i, 2) === '<<') { depth += 1; i += 2; continue; }
      if (text.substr(i, 2) === '>>') {
        depth -= 1; i += 2;
        if (depth === 0) return text.slice(from, i);
        continue;
      }
      i += 1;
    }
    return text.slice(from);
  }

  async function pdfObjects(bytes) {
    var text = latin1(bytes);
    var objects = {};
    var re = /(\d+)\s+(\d+)\s+obj\b/g, match;
    while ((match = re.exec(text)) !== null) {
      var number = Number(match[1]);
      var bodyStart = match.index + match[0].length;
      var endIndex = text.indexOf('endobj', bodyStart);
      var body = text.slice(bodyStart, endIndex < 0 ? text.length : endIndex);
      var dictStart = body.indexOf('<<');
      var dict = dictStart >= 0 ? pdfDictAt(body, dictStart) : '';
      var entry = { num: number, dict: dict, body: body, stream: null };
      var streamAt = body.indexOf('stream', dict ? dictStart + dict.length : 0);
      if (streamAt >= 0) {
        var dataStart = streamAt + 'stream'.length;
        if (body.charCodeAt(dataStart) === 13) dataStart += 1;
        if (body.charCodeAt(dataStart) === 10) dataStart += 1;
        var dataEnd = body.indexOf('endstream', dataStart);
        if (dataEnd < 0) dataEnd = body.length;
        /* /Length is authoritative when it is a direct number. Without it the
         * end-of-line before `endstream` would be handed to the decompressor
         * as trailing garbage, which is a hard error rather than something it
         * ignores, so trim it.
         *
         * The number must be the whole value: the lookahead requires the next
         * thing to be another key, the end of the dictionary, or nothing. A
         * mere "not an indirect reference" test lets the engine backtrack —
         * "/Length 12 0 R" then matches with (\d+) = "1", and a 435-byte
         * stream is cut to one byte. */
        var declared = /\/Length[ \t\r\n]+(\d+)[ \t\r\n]*(?=\/|>>|$)/.exec(dict);
        if (declared && Number(declared[1]) <= dataEnd - dataStart) {
          dataEnd = dataStart + Number(declared[1]);
        } else {
          while (dataEnd > dataStart &&
                 (body.charCodeAt(dataEnd - 1) === 10 ||
                  body.charCodeAt(dataEnd - 1) === 13)) {
            dataEnd -= 1;
          }
        }
        entry.rawStream = bytes.subarray(
          bodyStart + dataStart, bodyStart + dataEnd);
      }
      objects[number] = entry;
    }
    return objects;
  }

  async function pdfStreamText(entry) {
    if (!entry || !entry.rawStream) return '';
    if (entry.stream !== null) return entry.stream;
    var data = entry.rawStream;
    var filter = entry.dict.indexOf('/FlateDecode') >= 0;
    if (filter) {
      try {
        data = await inflateStream(data);
      } catch (e) {
        entry.stream = '';
        return '';
      }
    } else if (/\/(LZW|RunLength|DCT|CCITTFax|JBIG2|JPX)Decode/.test(entry.dict)) {
      /* an image or a filter this reader does not implement: no text in it */
      entry.stream = '';
      return '';
    }
    entry.stream = latin1(data);
    return entry.stream;
  }

  /* A ToUnicode CMap, reduced to the code -> string map the text needs. */
  function parseToUnicode(cmap) {
    var map = {};
    function decodeHex(hex) {
      var out = '';
      for (var i = 0; i + 3 < hex.length + 1; i += 4) {
        out += String.fromCharCode(parseInt(hex.substr(i, 4), 16));
      }
      return out;
    }
    var charRe = /beginbfchar([\s\S]*?)endbfchar/g, block;
    while ((block = charRe.exec(cmap)) !== null) {
      var pair = /<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>/g, hit;
      while ((hit = pair.exec(block[1])) !== null) {
        map[parseInt(hit[1], 16)] = decodeHex(hit[2]);
      }
    }
    var rangeRe = /beginbfrange([\s\S]*?)endbfrange/g;
    while ((block = rangeRe.exec(cmap)) !== null) {
      var simple = /<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>/g, span;
      while ((span = simple.exec(block[1])) !== null) {
        var lo = parseInt(span[1], 16), hi = parseInt(span[2], 16);
        var base = parseInt(span[3], 16);
        for (var code = lo; code <= hi && code - lo < 65536; code++) {
          map[code] = String.fromCharCode(base + (code - lo));
        }
      }
    }
    return map;
  }

  /* A PDF string literal: (text) with escapes, or <hex>. */
  function pdfStringBytes(token) {
    var out = [];
    if (token.charAt(0) === '<') {
      var hex = token.slice(1, -1).replace(/[^0-9A-Fa-f]/g, '');
      if (hex.length % 2) hex += '0';
      for (var h = 0; h < hex.length; h += 2) out.push(parseInt(hex.substr(h, 2), 16));
      return out;
    }
    var body = token.slice(1, -1);
    for (var i = 0; i < body.length; i++) {
      var ch = body.charAt(i);
      if (ch !== '\\') { out.push(body.charCodeAt(i)); continue; }
      var next = body.charAt(i + 1);
      var escapes = { n: 10, r: 13, t: 9, b: 8, f: 12, '(': 40, ')': 41, '\\': 92 };
      if (next in escapes) { out.push(escapes[next]); i += 1; continue; }
      if (/[0-7]/.test(next)) {
        var oct = '';
        while (oct.length < 3 && /[0-7]/.test(body.charAt(i + 1))) {
          oct += body.charAt(i + 1); i += 1;
        }
        out.push(parseInt(oct, 8));
        continue;
      }
      if (next === '\n') { i += 1; continue; }   /* line continuation */
      out.push(body.charCodeAt(i + 1)); i += 1;
    }
    return out;
  }

  function decodeWithFont(bytes, font) {
    var text = '', i;
    if (font && font.twoByte) {
      for (i = 0; i + 1 < bytes.length; i += 2) {
        var code = (bytes[i] << 8) | bytes[i + 1];
        text += font.map && code in font.map ? font.map[code]
          : String.fromCharCode(code);
      }
      return text;
    }
    for (i = 0; i < bytes.length; i++) {
      text += font && font.map && bytes[i] in font.map
        ? font.map[bytes[i]] : String.fromCharCode(bytes[i]);
    }
    return text;
  }

  /* Run one page's content stream and collect placed text.
   *
   * Only the text-positioning subset of the operator set is interpreted: the
   * text matrix, the line matrix, the showing operators and the font. That is
   * enough to know where each run of characters landed, which is what turns a
   * stream of glyphs back into lines and columns. */
  function runContentStream(content, fonts) {
    var placed = [];
    var tm = null, tlm = null, font = null, leading = 0, fontSize = 1;
    var stack = [];
    var token = /\/([^\s/<>\[\]()]+)|(\((?:\\.|[^\\()])*\))|(<[0-9A-Fa-f\s]*>)|(\[)|(\])|(-?[\d.]+)|([A-Za-z'"*]+)/g;
    var hit, operands = /** @type {Rec[]} */ ([]), inArray = false,
      arrayItems = /** @type {Rec[]} */ ([]);

    function place(bytes) {
      if (!tm) return;
      var text = decodeWithFont(bytes, font);
      if (!text) return;
      placed.push({ x: tm[4], y: tm[5], size: fontSize * Math.abs(tm[3] || 1), text: text });
      /* advance crudely: enough to keep separate runs apart, not a metrics
       * engine - the gap test below only needs relative positions */
      tm[4] += text.length * fontSize * 0.5;
    }
    function setMatrix(values) {
      tm = values.slice(); tlm = values.slice();
    }
    function nextLine(tx, ty) {
      if (!tlm) tlm = [1, 0, 0, 1, 0, 0];
      tlm[4] += tx; tlm[5] += ty;
      tm = tlm.slice();
    }

    while ((hit = token.exec(content)) !== null) {
      if (hit[1] !== undefined) {                      /* /Name */
        operands.push({ name: hit[1] });
        continue;
      }
      if (hit[2] !== undefined || hit[3] !== undefined) {    /* string */
        var value = { str: pdfStringBytes(hit[2] !== undefined ? hit[2] : hit[3]) };
        if (inArray) arrayItems.push(value); else operands.push(value);
        continue;
      }
      if (hit[4] !== undefined) { inArray = true; arrayItems = []; continue; }
      if (hit[5] !== undefined) {
        inArray = false; operands.push({ array: arrayItems }); continue;
      }
      if (hit[6] !== undefined) {
        var num = Number(hit[6]);
        if (inArray) arrayItems.push({ num: num }); else operands.push({ num: num });
        continue;
      }
      var op = hit[7];
      var nums = operands.filter(function (o) { return 'num' in o; })
        .map(function (o) { return o.num; });
      switch (op) {
        case 'BT': setMatrix([1, 0, 0, 1, 0, 0]); break;
        case 'ET': tm = null; break;
        case 'q': stack.push({ font: font, size: fontSize }); break;
        case 'Q':
          var saved = stack.pop();
          if (saved) { font = saved.font; fontSize = saved.size; }
          break;
        case 'Tf':
          var named = operands.filter(function (o) { return 'name' in o; });
          if (named.length) font = fonts[named[named.length - 1].name] || null;
          if (nums.length) fontSize = nums[nums.length - 1];
          break;
        case 'TL': if (nums.length) leading = nums[nums.length - 1]; break;
        case 'Td': if (nums.length >= 2) nextLine(nums[0], nums[1]); break;
        case 'TD':
          if (nums.length >= 2) { leading = -nums[1]; nextLine(nums[0], nums[1]); }
          break;
        case 'Tm': if (nums.length >= 6) setMatrix(nums.slice(0, 6)); break;
        case 'T*': nextLine(0, -leading); break;
        case 'Tj': case '\'': case '"':
          if (op !== 'Tj') nextLine(0, -leading);
          var strings = operands.filter(function (o) { return 'str' in o; });
          if (strings.length) place(strings[strings.length - 1].str);
          break;
        case 'TJ':
          var arrays = operands.filter(function (o) { return 'array' in o; });
          if (arrays.length) {
            arrays[arrays.length - 1].array.forEach(function (piece) {
              if ('str' in piece) place(piece.str);
              /* a large negative kern is how PDF writers space words */
              else if ('num' in piece && tm && piece.num < -120) {
                tm[4] += -piece.num / 1000 * fontSize;
                placed.push({ x: tm[4], y: tm[5], size: fontSize, text: ' ' });
              }
            });
          }
          break;
        default: break;
      }
      operands = [];
    }
    return placed;
  }

  /* Glyph runs -> lines of words. Runs land in drawing order, not reading
   * order, so they are grouped by baseline and sorted across the page. */
  function placedToLines(placed) {
    var lines = [];
    placed.forEach(function (run) {
      if (!run.text.trim() && run.text !== ' ') return;
      var tolerance = Math.max(run.size * 0.5, 2);
      var line = null;
      for (var i = 0; i < lines.length; i++) {
        if (Math.abs(lines[i].y - run.y) <= tolerance) { line = lines[i]; break; }
      }
      if (!line) { line = { y: run.y, runs: [] }; lines.push(line); }
      line.runs.push(run);
    });
    lines.sort(function (a, b) { return b.y - a.y; });
    return lines.map(function (line) {
      line.runs.sort(function (a, b) { return a.x - b.x; });
      var words = [], current = null;
      line.runs.forEach(function (run) {
        var gap = current === null ? 0 : run.x - current.end;
        if (current && gap > current.size * 0.28) {
          words.push(current); current = null;
        }
        if (!current) {
          current = { x: run.x, end: run.x, size: run.size || 10, text: '' };
        }
        current.text += run.text;
        current.end = run.x + run.text.length * (run.size || 10) * 0.5;
        current.size = run.size || current.size;
      });
      if (current) words.push(current);
      words = words.map(function (w) {
        return { x: w.x, end: w.end, text: w.text.replace(/\s+/g, ' ').trim() };
      }).filter(function (w) { return w.text; });
      return { y: line.y, words: words };
    }).filter(function (line) { return line.words.length; });
  }

  function lineText(line) {
    var out = '';
    line.words.forEach(function (word, i) {
      if (i === 0) { out += word.text; return; }
      /* three spaces mark a column break, which is what _split_line looks for */
      var gap = word.x - line.words[i - 1].end;
      out += gap > 14 ? '   ' + word.text : ' ' + word.text;
    });
    return out;
  }

  /* Tables, from the layout rather than from ruling lines.
   *
   * pdfplumber finds a table by its drawn rules; that needs the graphics
   * operators and the page's line art. Here the same job is done from word
   * positions: a run of consecutive lines of two or more columns that share a
   * column structure is a table. It finds the tables on a generated field
   * sheet, and it is honest about what it is - the page says so, and every
   * numeric cell that does not parse is flagged for review either way.
   *
   * A line's columns are its pieces between column breaks (the gaps lineText
   * writes as three spaces), as pdf_text.py _tables_from_lines counts them.
   * The Python reader counted words, so a caption above the headings became
   * the header there, and a note under the table a reading. */
  function tablesFromLines(lines, isHeaderLine) {
    var tables = [];
    var run = [];

    function flush() {
      if (run.length >= 3) {
        var columns = columnPositions(run);
        if (columns.length >= 2) {
          var grid = run.map(function (line) { return toCells(line, columns); });
          var header = grid.shift();
          if (grid.length) tables.push({ columns: header, rows: grid });
        }
      }
      run = [];
    }

    lines.forEach(function (line) {
      /* the header block is a two-column layout too, but its lines are
       * label/value pairs that have already been read as header fields;
       * folding them into the reading table would put "Community: Rokel"
       * where an AB/2 spacing belongs */
      if (splitHeaderLine(lineText(line)).length >= 2 &&
          !(isHeaderLine && isHeaderLine(line))) {
        run.push(line);
      } else {
        flush();
      }
    });
    flush();
    return tables;
  }

  /* Column edges: word start positions that recur down the block. */
  function columnPositions(lines) {
    var starts = [];
    lines.forEach(function (line) {
      line.words.forEach(function (word) { starts.push(word.x); });
    });
    starts.sort(function (a, b) { return a - b; });
    var clusters = [];
    starts.forEach(function (x) {
      var last = clusters[clusters.length - 1];
      if (last && x - last.at <= 8) { last.n += 1; last.at = (last.at + x) / 2; return; }
      clusters.push({ at: x, n: 1 });
    });
    return clusters.filter(function (cluster) {
      return cluster.n >= Math.max(2, Math.floor(lines.length * 0.5));
    }).map(function (cluster) { return cluster.at; });
  }

  function toCells(line, columns) {
    var cells = columns.map(function () { return ''; });
    line.words.forEach(function (word) {
      var index = 0;
      for (var i = 0; i < columns.length; i++) {
        if (word.x >= columns[i] - 8) index = i;
      }
      cells[index] = cells[index] ? cells[index] + ' ' + word.text : word.text;
    });
    return cells;
  }

  var NUMERIC_COLUMN_MARKERS = ['(m)', 'm)', 'ohm', 'rate', 'level', 'depth',
    'time', 'value', 'ab/2', 'mn'];

  /** Numeric columns should hold numbers; an empty cell in a numeric column,
   * non-numeric junk and a number with something else in the cell are all
   * review items. parseNumber takes the first number in a cell, so a
   * scanner's "12O.4" used to pass as clean and reach the template as 12: the
   * whole cell has to be the number, bar a unit after it (isWholeNumber).
   * @param {*} cell
   * @param {*} column the column's header
   * @returns {[number, string]}
   */
  function cellConfidence(cell, column) {
    var lower = String(column || '').toLowerCase();
    var numeric = NUMERIC_COLUMN_MARKERS.some(function (marker) {
      return lower.indexOf(marker) >= 0;
    });
    if (!numeric) return [1.0, ''];
    var reasons = phraseTable('extraction.cell_reason');
    if (cell === '') return [0.6, reasons.empty];
    if (parseNumber(cell) === null) return [0.4, reasons.unreadable];
    if (!isWholeNumber(cell)) return [0.5, reasons.partial];
    return [1.0, ''];
  }

  function splitHeaderLine(line) {
    return line.split(/\t+|\s{3,}/).filter(function (part) { return part.trim(); });
  }

  /**
   * @param {Uint8Array} bytes
   * @param {string} [sourceName]
   */
  async function extractPdfText(bytes, sourceName) {
    var objects = await pdfObjects(bytes);
    var numbers = Object.keys(objects).map(Number).sort(function (a, b) { return a - b; });
    var pages = numbers.map(function (n) { return objects[n]; })
      .filter(function (o) { return /\/Type\s*\/Page\b/.test(o.dict); });
    if (!pages.length) {
      throw new Error('No pages found in that PDF. If it is a photograph or a ' +
        'scan with no text layer, use the AI assisted extraction instead.');
    }

    var header = [], tables = [], uncertain = [], allText = [];
    /* null-prototype: the keys are canonical field names, and a bare object
     * would report "constructor" as already seen */
    var seen = Object.create(null);

    for (var p = 0; p < pages.length; p++) {
      var page = pages[p];
      /* fonts declared for this page, so a ToUnicode CMap can be applied.
       * null-prototype: the names come from the document, and a font called
       * /constructor would otherwise resolve to Object.prototype's. */
      var fonts = Object.create(null);
      var resourceMatch = /\/Font\s*<<([\s\S]*?)>>/.exec(page.dict);
      if (!resourceMatch) {
        var resourceRefs = pdfRefs(page.dict, 'Resources');
        if (resourceRefs.length && objects[resourceRefs[0]]) {
          resourceMatch = /\/Font\s*<<([\s\S]*?)>>/.exec(objects[resourceRefs[0]].dict);
        }
      }
      if (resourceMatch) {
        var fontRe = /\/([^\s/]+)\s+(\d+)\s+\d+\s+R/g, fontHit;
        while ((fontHit = fontRe.exec(resourceMatch[1])) !== null) {
          var fontObject = objects[Number(fontHit[2])];
          if (!fontObject) continue;
          /** @type {Rec} */
          var spec = { twoByte: /\/Type0\b/.test(fontObject.dict), map: null };
          var toUnicode = pdfRefs(fontObject.dict, 'ToUnicode');
          if (toUnicode.length && objects[toUnicode[0]]) {
            spec.map = parseToUnicode(await pdfStreamText(objects[toUnicode[0]]));
          }
          fonts[fontHit[1]] = spec;
        }
      }

      var content = '';
      var contentRefs = pdfRefs(page.dict, 'Contents');
      for (var r = 0; r < contentRefs.length; r++) {
        content += await pdfStreamText(objects[contentRefs[r]]) + '\n';
      }
      if (!content.trim()) continue;

      var lines = placedToLines(runContentStream(content, fonts));
      allText.push(lines.map(lineText).join('\n'));

      /* header labels from text lines ("Community: Rokel   Date: ...") */
      var headerLines = [];
      lines.forEach(function (line) {
        var matched = false;
        splitHeaderLine(lineText(line)).forEach(function (part) {
          var split = splitInlineValue(part);
          var key = matchLabel(split[0]);
          if (!key || !split[1]) return;
          matched = true;
          if (key in seen) return;
          seen[key] = true;
          header.push(extractedField(key, cleanText(split[1]), 0.95));
        });
        if (matched) headerLines.push(line);
      });

      tablesFromLines(lines, function (line) {
        return headerLines.indexOf(line) >= 0;
      }).forEach(function (table) {
        var index = tables.length;
        var confidences = [];
        table.rows.forEach(function (row, rowIndex) {
          var rowConfidence = 1.0;
          row.forEach(function (cell, columnIndex) {
            var judged = cellConfidence(
              cell, columnIndex < table.columns.length ? table.columns[columnIndex] : '');
            if (judged[0] < 1.0) {
              uncertain.push({
                table_index: index, row: rowIndex, column: columnIndex,
                reason: judged[1],
              });
              rowConfidence = Math.min(rowConfidence, judged[0]);
            }
          });
          confidences.push(rowConfidence);
        });
        tables.push({
          title: 'Table ' + (index + 1), columns: table.columns,
          rows: table.rows, row_confidence: confidences,
        });
      });
    }

    var blob = allText.join('\n');
    if (!blob.trim()) throw new Error(phrase('extraction.no_text_layer'));
    return {
      source: sourceName || 'document.pdf',
      document_kind: guessDocumentKind(blob),
      header: header, tables: tables, uncertain_cells: uncertain,
      notes: 'Rule based extraction from the PDF text layer, read in the browser.',
      extractor: 'pdf-text',
      text: blob,
    };
  }

  /* --- the review workbook --------------------------------------------------- */

  /** @param {Rec} document an extracted document */
  function reviewWorkbookSheets(document) {
    var sheets = [];
    /** @type {Array<Array<*>>} */
    var headerRows = [['Field', 'Value', 'Confidence']];
    (document.header || []).forEach(function (field) {
      var flag = field.needs_review;
      headerRows.push([
        { v: field.name, flag: flag },
        { v: field.value, flag: flag },
        { v: pyRound(field.confidence, 2), flag: flag },
      ]);
    });
    sheets.push({ name: 'Header', rows: headerRows, widths: [28, 32, 12] });

    var flagged = {};
    (document.uncertain_cells || []).forEach(function (cell) {
      flagged[cell.table_index + ':' + cell.row + ':' + cell.column] = cell.reason;
    });

    (document.tables || []).forEach(function (table, index) {
      /* the title row is bolded by writeXlsx (row 0); the column headings are
       * row 1 and have to ask, as they do in the openpyxl workbook */
      var rows = [[table.title], table.columns.map(function (column) {
        return { v: column, bold: true };
      })];
      table.rows.forEach(function (row, rowIndex) {
        var lowConfidence = confidenceForRow(table, rowIndex) < REVIEW_THRESHOLD;
        rows.push(row.map(function (cell, columnIndex) {
          var key = index + ':' + rowIndex + ':' + columnIndex;
          return { v: cell, flag: lowConfidence || (key in flagged) };
        }));
      });
      sheets.push({ name: ('Table ' + (index + 1)).slice(0, 31), rows: rows });
    });

    var items = reviewItems(document);
    /** @type {Array<Array<*>>} */
    var reviewRows = [['Items needing manual review']];
    if (items.length) {
      items.forEach(function (item) { reviewRows.push([{ v: item, flag: true }]); });
    } else {
      reviewRows.push(['None: all values extracted with high confidence.']);
    }
    reviewRows.push([]);
    reviewRows.push(['Source: ' + document.source]);
    reviewRows.push(['Extractor: ' + document.extractor]);
    reviewRows.push(['Document kind: ' + document.document_kind]);
    if (document.notes) reviewRows.push(['Notes: ' + document.notes]);
    sheets.push({ name: 'Review', rows: reviewRows, widths: [100] });
    return sheets;
  }

  /** The standard VES template, filled from an extracted VES sheet. Header
   * fields go through the same label patterns the parsers use, so the filled
   * workbook reads back through the normal reader after review.
   *
   * The readings go in as the sheet has them, under headings the VES reader
   * reads the way the sheet meant them (review.py fill_ves_template): a
   * half-spacing column is headed "MN/2 (m)", so the reader doubles it, and a
   * sheet that records resistances has them headed "Resistance (ohm)", with
   * its K column beside them where it has one. A table whose readings cannot
   * be placed that way is refused, with the reason.
   * @param {Rec} document an extracted document of kind 'ves'
   * @param {Grid} blankRows the template's own rows
   */
  function fillVesTemplateSheets(document, blankRows) {
    if (document.document_kind !== 'ves') {
      throw new Error("Filling the VES template needs a document of kind 'ves'.");
    }
    if (!(document.tables || []).length) {
      throw new Error('No data table was extracted from that sheet.');
    }
    var table = document.tables[0];
    var layout = vesTemplateColumns(table);
    if (layout.missing.length) {
      var reason = vesUnplaced(table, layout.missing);
      throw new Error(reason.charAt(0).toUpperCase() + reason.slice(1) + '.');
    }
    var placed = layout.placed;
    var rows = blankRows.map(function (row) { return (row || []).slice(); });

    /* canonical key -> [row, column] in the template, 0-based */
    var cellMap = {
      client: [1, 1], community: [1, 3],
      project: [2, 1], sounding_id: [2, 3],
      district: [3, 1], chiefdom: [3, 3],
      easting: [4, 1], northing: [4, 3],
      elevation_m: [5, 1], date: [5, 3],
      supervisor: [6, 1], instrument: [6, 3],
    };
    /* the blank template's own sounding number is not the sheet's: left in,
     * it was read back as if the sheet had given it */
    if (rows[cellMap.sounding_id[0]]) rows[cellMap.sounding_id[0]][cellMap.sounding_id[1]] = '';
    (document.header || []).forEach(function (field) {
      /* The AI path names a field the way the sheet does ("Sounding Number"),
       * which the label patterns resolve. The text-layer path has already
       * resolved it, so its name is the canonical key itself - and a canonical
       * key does not match its own pattern ("sounding_id" is not "sounding
       * number"). Accept both, or the field silently fails to land. */
      var key = field.name in cellMap ? field.name : matchLabel(field.name);
      var target = cellMap[key];
      if (!target) return;
      while (rows.length <= target[0]) rows.push([]);
      rows[target[0]][target[1]] = { v: field.value, flag: field.needs_review };
    });

    var flagged = {};
    (document.uncertain_cells || []).forEach(function (cell) {
      if (cell.table_index === 0) flagged[cell.row + ':' + cell.column] = true;
    });

    /* the blank template's reading grid starts on the row after the column
     * headings; everything below it is replaced by the extracted readings */
    var firstReading = 9;
    for (var i = 0; i < rows.length; i++) {
      if ((rows[i] || [])[0] === 'No.') { firstReading = i + 1; break; }
    }
    rows.length = firstReading;
    /* template column (0-based) <- the extracted table's column, under the
     * blank template's own headings, changed where the sheet's columns are
     * not what they say */
    var headings = (rows[firstReading - 1] || []).slice(0, 4);
    /** @type {Array<[number, number]>} */
    var targets = [[placed.ab2, 1]];
    if ('mn' in placed) {
      targets.push([placed.mn, 2]);
    } else if ('mn_half' in placed) {
      targets.push([placed.mn_half, 2]);
      headings[2] = 'MN/2 (m)';
    }
    if ('rho' in placed) {
      targets.push([placed.rho, 3]);
    } else {
      targets.push([placed.resistance, 3]);
      headings[3] = 'Resistance (ohm)';
      if ('k' in placed) {
        targets.push([placed.k, 4]);
        headings.push('K');
      }
    }
    rows[firstReading - 1] = headings;
    table.rows.forEach(function (row, index) {
      /** @type {Array<*>} */
      var out = headings.map(function () { return ''; });
      out[0] = index + 1;
      targets.forEach(function (pair) {
        if (pair[0] >= row.length) return;
        out[pair[1]] = { v: row[pair[0]], flag: (index + ':' + pair[0]) in flagged };
      });
      rows.push(out);
    });
    return rows;
  }

  /* --- AI assisted extraction ------------------------------------------------
   *
   * The same request the Python ClaudeExtractor makes, sent straight from the
   * page. The key never leaves the browser: there is no server here to hold
   * one, so the operator supplies it on the Settings page and it is stored -
   * clearly labelled - alongside the rest of the local session.
   */

  var EXTRACTION_MODEL = 'claude-opus-5';

  var EXTRACTION_SCHEMA = {
    type: 'object',
    properties: {
      document_kind: {
        type: 'string',
        enum: ['ves', 'pumping_test', 'drilling_log', 'water_quality', 'unknown'],
      },
      header: {
        type: 'array',
        items: {
          type: 'object',
          properties: {
            name: { type: 'string' },
            value: { type: 'string' },
            confidence: {
              type: 'number',
              description: '0 to 1; below 0.85 means needs manual review',
            },
          },
          required: ['name', 'value', 'confidence'],
          additionalProperties: false,
        },
      },
      tables: {
        type: 'array',
        items: {
          type: 'object',
          properties: {
            title: { type: 'string' },
            columns: { type: 'array', items: { type: 'string' } },
            rows: { type: 'array', items: { type: 'array', items: { type: 'string' } } },
          },
          required: ['title', 'columns', 'rows'],
          additionalProperties: false,
        },
      },
      uncertain_cells: {
        type: 'array',
        items: {
          type: 'object',
          properties: {
            table_index: { type: 'integer' },
            row: { type: 'integer' },
            column: { type: 'integer' },
            reason: { type: 'string' },
          },
          required: ['table_index', 'row', 'column', 'reason'],
          additionalProperties: false,
        },
      },
      notes: { type: 'string' },
    },
    required: ['document_kind', 'header', 'tables', 'uncertain_cells', 'notes'],
    additionalProperties: false,
  };

  var EXTRACTION_PROMPT = [
    'You are transcribing a groundwater field data sheet from Sierra Leone',
    '(vertical electrical sounding, pumping test, drilling log or water quality',
    'laboratory sheet).',
    '',
    'Extract:',
    '1. document_kind: which sheet type this is.',
    '2. header: every label/value pair from the header block (community, client,',
    '   district, date, borehole reference, static water level, GPS coordinates,',
    '   elevation, supervisor and so on). Use the label wording from the sheet.',
    '3. tables: every data table, with its column headings and every row, in',
    '   order. Transcribe numbers exactly as written, including leading zeros',
    '   (for example 078.7). Do not invent values for illegible cells; write an',
    '   empty string and flag the cell.',
    '4. uncertain_cells: every table cell you are not fully certain about',
    '   (handwriting hard to read, smudges, ambiguous digits), with a short',
    '   reason. Indices are zero based; row counts data rows only.',
    '5. Give each header field a confidence between 0 and 1. Use values below',
    '   0.85 whenever a reasonable person could read the handwriting differently.',
    '',
    'Accuracy matters more than completeness: flag anything doubtful rather than',
    'guessing silently.',
  ].join('\n');

  /**
   * @param {Rec} payload what the model returned
   * @param {string} [source]
   */
  function extractionDocumentFrom(payload, source) {
    return {
      source: source,
      document_kind: payload.document_kind || 'unknown',
      header: (payload.header || []).map(function (f) {
        return extractedField(f.name || '', f.value || '',
          f.confidence === undefined ? 0.5 : Number(f.confidence));
      }),
      tables: (payload.tables || []).map(function (t, i) {
        return {
          title: t.title || ('Table ' + (i + 1)),
          columns: (t.columns || []).map(String),
          rows: (t.rows || []).map(function (row) { return (row || []).map(String); }),
          row_confidence: [],
        };
      }),
      uncertain_cells: (payload.uncertain_cells || []).map(function (c) {
        return {
          table_index: Number(c.table_index || 0), row: Number(c.row || 0),
          column: Number(c.column || 0), reason: c.reason || '',
        };
      }),
      notes: payload.notes || '',
      extractor: 'claude',
    };
  }

  /** @param {Rec} [options] apiKey, base64, mediaType, model, source */
  async function extractWithClaude(options) {
    var opts = options || {};
    if (!opts.apiKey) {
      throw new Error('No Anthropic API key is set. Add one on the Settings ' +
        'page to use the AI assisted extraction.');
    }
    var isPdf = opts.mediaType === 'application/pdf';
    var block = isPdf
      ? { type: 'document',
        source: { type: 'base64', media_type: 'application/pdf', data: opts.base64 } }
      : { type: 'image',
        source: { type: 'base64', media_type: opts.mediaType, data: opts.base64 } };

    var response = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'x-api-key': opts.apiKey,
        'anthropic-version': '2023-06-01',
        /* the documented opt-in for calling the API from a page; without it
         * the browser request is refused outright */
        'anthropic-dangerous-direct-browser-access': 'true',
      },
      body: JSON.stringify({
        model: opts.model || EXTRACTION_MODEL,
        max_tokens: 16000,
        thinking: { type: 'adaptive' },
        output_config: { format: { type: 'json_schema', schema: EXTRACTION_SCHEMA } },
        messages: [{
          role: 'user',
          content: [block, { type: 'text', text: EXTRACTION_PROMPT }],
        }],
      }),
    });

    if (!response.ok) {
      var detail = '';
      try {
        var body = await response.json();
        detail = (body.error && body.error.message) || '';
      } catch (e) { detail = ''; }
      throw new Error('The Claude API answered ' + response.status +
        (detail ? ': ' + detail : '.'));
    }
    var message = await response.json();
    return extractionDocumentFrom(replyPayload(message), opts.source || 'scan');
  }

  /** The transcription a reply carries, or the reason it carries none.
   * claude.py _reply_payload. A refusal leaves content empty, and hitting the
   * output cap can leave only thinking blocks or part of the JSON, which went
   * straight to JSON.parse and came back as "Unexpected end of JSON input":
   * the reply is refused for its stop reason before it is parsed, and
   * anything else that is not JSON is refused naming it.
   * @param {Rec} message the API's reply
   * @returns {Rec}
   */
  function replyPayload(message) {
    var stopReason = String(message.stop_reason || 'unknown');
    if (stopReason === 'refusal') throw new Error(phrase('extraction.declined'));
    if (stopReason === 'max_tokens') throw new Error(phrase('extraction.cut_off'));
    var textBlock = (message.content || []).filter(function (b) {
      return b.type === 'text';
    })[0];
    if (!textBlock) {
      throw new Error(phrase('extraction.no_transcription', { stop_reason: stopReason }));
    }
    var payload;
    try {
      payload = JSON.parse(textBlock.text);
    } catch (e) {
      throw new Error(phrase('extraction.unreadable_reply', { stop_reason: stopReason }));
    }
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
      throw new Error(phrase('extraction.unreadable_reply', { stop_reason: stopReason }));
    }
    return payload;
  }

  /* --- a pumping test written on a Word field sheet -------------------------
   *
   * groundwater/ingestion/pumping.py read_pumping_docx. Some crews are handed
   * a .docx sheet rather than the workbook, and refusing it means the readings
   * get retyped - which is where transcription errors come from. A .docx is a
   * ZIP holding one XML document, so the whole reader is a parse and two
   * walks: paragraphs give the header block, and the table carrying the most
   * Time/Water Level column groups gives the readings.
   */
  /**
   * @param {Uint8Array|ArrayBuffer} bytes
   * @param {string} [source]
   * @returns {Promise<PumpingTest>}
   */
  async function readPumpingDocx(bytes, source) {
    var files = await GWT.support.unzip(bytes);
    var xml = files['word/document.xml'];
    if (!xml) {
      throw new Error('That .docx has no word/document.xml; it is not a Word ' +
        'document this reader can open.');
    }
    var doc = new DOMParser().parseFromString(
      new TextDecoder().decode(xml), 'application/xml');
    var W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main';

    function textOf(node) {
      var runs = node.getElementsByTagNameNS(W, 't');
      var out = '';
      for (var i = 0; i < runs.length; i++) out += runs[i].textContent;
      return out;
    }

    /* This table's own rows and each row's own cells - walking the element
     * children rather than getElementsByTagName, so a nested table's rows do
     * not appear as extra rows of the table that contains it. */
    function gridOf(table) {
      var grid = [];
      for (var r = 0; r < table.childNodes.length; r++) {
        var row = table.childNodes[r];
        if (row.nodeType !== 1 || row.localName !== 'tr') continue;
        var cells = [];
        for (var c = 0; c < row.childNodes.length; c++) {
          var cell = row.childNodes[c];
          if (cell.nodeType === 1 && cell.localName === 'tc') {
            cells.push(textOf(cell).trim());
          }
        }
        grid.push(cells);
      }
      return grid;
    }

    var body = doc.getElementsByTagNameNS(W, 'body')[0];
    if (!body) throw new Error('That .docx has no document body.');

    /* paragraphs at the top level only: a paragraph inside a table cell is
     * part of that cell, not of the header block */
    var headerGrid = [];
    var tables = [];
    for (var i = 0; i < body.childNodes.length; i++) {
      var node = /** @type {Element} */ (body.childNodes[i]);
      if (node.nodeType !== 1) continue;
      if (node.localName === 'p') {
        var text = textOf(node).trim();
        if (!text) continue;
        headerGrid.push(text.split(/\t+|\s{3,}/).filter(function (part) {
          return part.trim();
        }));
      } else if (node.localName === 'tbl') {
        tables.push(gridOf(node));
      }
    }

    var best = null, bestCount = 0;
    tables.forEach(function (grid) {
      var located = findGroups(grid);
      if (located && located.groups.length > bestCount) {
        best = grid; bestCount = located.groups.length;
      }
    });
    if (!best) {
      throw new Error('No pumping test table was found in ' + (source || 'that .docx') +
        '. The reader looks for a table with Time and Water Level columns.');
    }
    return pumpingFromGrid(headerGrid.concat(best), source || 'field sheet.docx');
  }

  Object.assign(C, {
    readPumpingDocx: readPumpingDocx,
    REVIEW_THRESHOLD: REVIEW_THRESHOLD,
    guessDocumentKind: guessDocumentKind, extractedField: extractedField,
    reviewItems: reviewItems, confidenceForRow: confidenceForRow,
    extractPdfText: extractPdfText, cellConfidence: cellConfidence,
    reviewWorkbookSheets: reviewWorkbookSheets,
    fillVesTemplateSheets: fillVesTemplateSheets,
    vesTemplateColumns: vesTemplateColumns, sheetReviewItems: sheetReviewItems,
    extractWithClaude: extractWithClaude, replyPayload: replyPayload,
    extractionDocumentFrom: extractionDocumentFrom,
    EXTRACTION_MODEL: EXTRACTION_MODEL, EXTRACTION_SCHEMA: EXTRACTION_SCHEMA,
    EXTRACTION_PROMPT: EXTRACTION_PROMPT,
  });

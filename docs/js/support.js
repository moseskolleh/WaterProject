/* support.js - shared runtime for the Groundwater Toolkit web app.
 *
 * Everything the app needs that is not groundwater science: DOM building,
 * number parsing that copes with how field sheets are actually written,
 * ZIP reading and writing (so .xlsx uploads and .docx downloads work with no
 * server and no third party library), CSV handling, the project store and the
 * small set of UI primitives the pages are assembled from.
 *
 * Loaded as a classic script so the app also runs from a file:// copy on a
 * laptop with no connection. Everything hangs off window.GWT.
 */
(function (global) {
  'use strict';

  var GWT = global.GWT || (global.GWT = {});
  var S = GWT.support = {};

  /* ---------------------------------------------------------------- DOM */

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }

  /* el('div.card', {id: 'x'}, [child, 'text']) */
  function el(spec, attrs, children) {
    var m = /^([a-zA-Z0-9-]+)?((?:[.#][^.#]+)*)$/.exec(spec);
    if (!m) throw new Error('bad element spec: ' + spec);
    var node = document.createElement(m[1] || 'div');
    var rest = m[2] || '';
    var parts = rest.match(/[.#][^.#]+/g) || [];
    parts.forEach(function (p) {
      if (p.charAt(0) === '#') node.id = p.slice(1);
      else node.classList.add(p.slice(1));
    });
    if (attrs && (typeof attrs !== 'object' || Array.isArray(attrs) ||
                  attrs instanceof Node)) {
      children = attrs; attrs = null;
    }
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        var v = attrs[k];
        if (v === null || v === undefined || v === false) return;
        if (k === 'style' && typeof v === 'object') {
          Object.keys(v).forEach(function (p) { node.style[p] = v[p]; });
        } else if (k === 'dataset') {
          Object.keys(v).forEach(function (p) { node.dataset[p] = v[p]; });
        } else if (k.slice(0, 2) === 'on' && typeof v === 'function') {
          node.addEventListener(k.slice(2).toLowerCase(), v);
        } else if (k === 'html') {
          node.innerHTML = v;
        } else if (k === 'text') {
          node.textContent = v;
        } else if (k in node && k !== 'list' && k !== 'form' && k !== 'type') {
          try { node[k] = v; } catch (e) { node.setAttribute(k, v); }
        } else {
          node.setAttribute(k, v === true ? '' : v);
        }
      });
    }
    append(node, children);
    return node;
  }

  function append(node, children) {
    if (children === null || children === undefined || children === false) return node;
    if (Array.isArray(children)) {
      children.forEach(function (c) { append(node, c); });
      return node;
    }
    if (children instanceof Node) { node.appendChild(children); return node; }
    node.appendChild(document.createTextNode(String(children)));
    return node;
  }

  function clear(node) {
    while (node && node.firstChild) node.removeChild(node.firstChild);
    return node;
  }

  /* SVG sibling of el(), for the chart module. */
  var SVG_NS = 'http://www.w3.org/2000/svg';
  function svgEl(tag, attrs, children) {
    var node = document.createElementNS(SVG_NS, tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        var v = attrs[k];
        if (v === null || v === undefined || v === false) return;
        if (k === 'text') { node.textContent = v; return; }
        if (k.slice(0, 2) === 'on' && typeof v === 'function') {
          node.addEventListener(k.slice(2).toLowerCase(), v); return;
        }
        node.setAttribute(k, v);
      });
    }
    append(node, children);
    return node;
  }

  /* ----------------------------------------------------------- numbers */

  /* Field sheets carry numbers as they were written by hand: leading zeros
   * ("078.7", GPS "0708958"), thousands separators, stray units, a lone dash
   * for "not recorded", parentheses for negatives. None of that should be
   * allowed to poison a reading. Returns null when there is no number. */
  function parseNum(value) {
    if (value === null || value === undefined) return null;
    if (typeof value === 'number') return isFinite(value) ? value : null;
    if (typeof value === 'boolean') return null;
    var s = String(value).trim();
    if (!s) return null;
    if (/^[-‐-―−.\s]*$/.test(s)) return null;   // "-", "--", "."
    if (/^(n\/?a|nil|none|nd|n\.d\.?|not\s+recorded|pending|\?)$/i.test(s)) return null;
    var negative = false;
    if (/^\(.*\)$/.test(s)) { negative = true; s = s.slice(1, -1); }
    s = s.replace(/[−‐-―]/g, '-');              // unicode minus/dashes
    s = s.replace(/[\s ']/g, '');                          // spaces, apostrophes
    /* Strip a trailing unit or annotation but keep exponents: 12.5m, 3.4 mg/l */
    s = s.replace(/^([+-]?[0-9.,]+(?:[eE][+-]?[0-9]+)?).*$/, '$1');
    /* 1,234.5 -> 1234.5 ; 1.234,5 -> 1234.5 ; 1,5 -> 1.5 */
    if (s.indexOf(',') >= 0 && s.indexOf('.') >= 0) {
      if (s.lastIndexOf(',') > s.lastIndexOf('.')) {
        s = s.replace(/\./g, '').replace(',', '.');
      } else {
        s = s.replace(/,/g, '');
      }
    } else if (s.indexOf(',') >= 0) {
      var groups = s.split(',');
      var thousands = groups.length > 1 && groups.slice(1).every(function (g) {
        return /^\d{3}$/.test(g);
      });
      s = thousands ? groups.join('') : s.replace(',', '.');
    }
    if (s === '' || s === '-' || s === '+') return null;
    var n = Number(s);
    if (!isFinite(n)) return null;
    return negative ? -n : n;
  }

  function isNum(v) { return typeof v === 'number' && isFinite(v); }

  /* Fixed decimals, but "-" when the value is missing so tables stay legible. */
  function fmt(value, decimals, dash) {
    if (!isNum(value)) return dash === undefined ? '–' : dash;
    var d = decimals === undefined ? 2 : decimals;
    var out = value.toFixed(d);
    if (Object.is(Number(out), -0)) out = (0).toFixed(d);
    return out;
  }

  /* Significant figures, for quantities whose magnitude varies wildly
   * (resistivities from 5 to 20 000 ohm-m, transmissivities from 0.01 to 500). */
  function sig(value, digits) {
    if (!isNum(value)) return '–';
    if (value === 0) return '0';
    var n = digits || 3;
    var mag = Math.floor(Math.log(Math.abs(value)) / Math.LN10);
    var dec = Math.max(0, n - 1 - mag);
    if (dec > 6) return value.toExponential(n - 1);
    if (Math.abs(value) >= Math.pow(10, n + 4)) return value.toExponential(n - 1);
    return value.toFixed(dec);
  }

  function thousands(value, decimals) {
    if (!isNum(value)) return '–';
    return value.toLocaleString('en-GB', {
      minimumFractionDigits: decimals === undefined ? 0 : decimals,
      maximumFractionDigits: decimals === undefined ? 0 : decimals,
    });
  }

  function money(value, decimals) {
    if (!isNum(value)) return '–';
    return 'US$ ' + thousands(value, decimals === undefined ? 2 : decimals);
  }

  function clamp(v, lo, hi) { return v < lo ? lo : (v > hi ? hi : v); }

  function round(value, step) {
    if (!isNum(value) || !step) return value;
    return Math.round(value / step) * step;
  }

  function mean(values) {
    var xs = values.filter(isNum);
    if (!xs.length) return null;
    return xs.reduce(function (a, b) { return a + b; }, 0) / xs.length;
  }

  function median(values) {
    var xs = values.filter(isNum).slice().sort(function (a, b) { return a - b; });
    if (!xs.length) return null;
    var mid = Math.floor(xs.length / 2);
    return xs.length % 2 ? xs[mid] : (xs[mid - 1] + xs[mid]) / 2;
  }

  function sum(values) {
    return values.filter(isNum).reduce(function (a, b) { return a + b; }, 0);
  }

  function range(n) {
    var out = [];
    for (var i = 0; i < n; i++) out.push(i);
    return out;
  }

  function linspace(a, b, n) {
    if (n < 2) return [a];
    var out = [], step = (b - a) / (n - 1);
    for (var i = 0; i < n; i++) out.push(a + step * i);
    return out;
  }

  function logspace(a, b, n) {
    return linspace(Math.log(a), Math.log(b), n).map(Math.exp);
  }

  /* ------------------------------------------------------------- dates */

  var MONTHS = ['january', 'february', 'march', 'april', 'may', 'june', 'july',
                'august', 'september', 'october', 'november', 'december'];

  /* Field sheets date things as "10/05/2018", "1st April, 2017" or an Excel
   * serial. All three have to land on the same day. Day-first is assumed for
   * the ambiguous slash form, which is how the Sierra Leone sheets are written. */
  function parseDate(value) {
    if (value === null || value === undefined || value === '') return null;
    if (value instanceof Date) return isNaN(value.getTime()) ? null : value;
    if (typeof value === 'number' && isFinite(value)) return excelSerialToDate(value);
    var s = String(value).trim();
    if (!s) return null;
    var m = /^(\d{4})-(\d{1,2})-(\d{1,2})/.exec(s);
    if (m) return mkDate(+m[1], +m[2], +m[3]);
    m = /^(\d{1,2})[\/.\-](\d{1,2})[\/.\-](\d{2,4})$/.exec(s);
    if (m) {
      var d = +m[1], mo = +m[2], y = +m[3];
      if (d > 12 && mo <= 12) { /* unambiguous day-first */ }
      else if (mo > 12 && d <= 12) { var t = d; d = mo; mo = t; }
      if (y < 100) y += y < 70 ? 2000 : 1900;
      return mkDate(y, mo, d);
    }
    m = /^(\d{1,2})\s*(?:st|nd|rd|th)?\s+([A-Za-z]+),?\s*(\d{4})$/.exec(s);
    if (m) {
      var mi = monthIndex(m[2]);
      if (mi >= 0) return mkDate(+m[3], mi + 1, +m[1]);
    }
    m = /^([A-Za-z]+)\s+(\d{1,2})\s*(?:st|nd|rd|th)?,?\s*(\d{4})$/.exec(s);
    if (m) {
      var mj = monthIndex(m[1]);
      if (mj >= 0) return mkDate(+m[3], mj + 1, +m[2]);
    }
    var parsed = new Date(s);
    return isNaN(parsed.getTime()) ? null : parsed;
  }

  function monthIndex(name) {
    var lower = String(name).toLowerCase();
    for (var i = 0; i < MONTHS.length; i++) {
      if (MONTHS[i].indexOf(lower) === 0 || lower.indexOf(MONTHS[i].slice(0, 3)) === 0) {
        if (MONTHS[i].slice(0, 3) === lower.slice(0, 3)) return i;
      }
    }
    return -1;
  }

  function mkDate(y, m, d) {
    var dt = new Date(Date.UTC(y, m - 1, d));
    return isNaN(dt.getTime()) ? null : dt;
  }

  /* Excel stores dates as days since 1900-01-00, with the 1900 leap year bug. */
  function excelSerialToDate(serial) {
    if (serial < 1) return null;
    var days = Math.floor(serial);
    if (days > 59) days -= 1;                       // skip the phantom 1900-02-29
    var ms = (days - 1) * 86400000 + Date.UTC(1900, 0, 1);
    var frac = serial - Math.floor(serial);
    return new Date(ms + Math.round(frac * 86400000));
  }

  function formatDate(value) {
    var d = parseDate(value);
    if (!d) return value ? String(value) : '';
    var dd = String(d.getUTCDate()).padStart(2, '0');
    var mm = String(d.getUTCMonth() + 1).padStart(2, '0');
    return dd + '/' + mm + '/' + d.getUTCFullYear();
  }

  function formatDateLong(value) {
    var d = parseDate(value);
    if (!d) return value ? String(value) : '';
    var month = MONTHS[d.getUTCMonth()];
    return d.getUTCDate() + ' ' + month.charAt(0).toUpperCase() + month.slice(1) +
      ' ' + d.getUTCFullYear();
  }

  function today() {
    var d = new Date();
    return new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  }

  /* ------------------------------------------------------------ strings */

  function slug(text) {
    return String(text || '').toLowerCase()
      .replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '') || 'item';
  }

  function titleCase(text) {
    return String(text || '').replace(/\w\S*/g, function (w) {
      return w.charAt(0).toUpperCase() + w.slice(1).toLowerCase();
    });
  }

  function escapeHtml(text) {
    return String(text === null || text === undefined ? '' : text)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function escapeXml(text) {
    return String(text === null || text === undefined ? '' : text)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&apos;')
      /* control characters are illegal in XML 1.0 and crash Word */
      .replace(/[\x00-\x08\x0b\x0c\x0e-\x1f]/g, '');
  }

  function plural(n, one, many) {
    return n === 1 ? one : (many || one + 's');
  }

  /* A sentence list: "a", "a and b", "a, b and c". */
  function joinList(items) {
    var xs = (items || []).filter(function (x) { return x !== null && x !== undefined && x !== ''; })
      .map(String);
    if (!xs.length) return '';
    if (xs.length === 1) return xs[0];
    return xs.slice(0, -1).join(', ') + ' and ' + xs[xs.length - 1];
  }

  function normaliseKey(text) {
    return String(text || '').toLowerCase().replace(/[^a-z0-9]+/g, '');
  }

  /* -------------------------------------------------------- byte helpers */

  function utf8(text) {
    return new TextEncoder().encode(text);
  }

  function concatBytes(chunks) {
    var total = chunks.reduce(function (a, c) { return a + c.length; }, 0);
    var out = new Uint8Array(total), at = 0;
    chunks.forEach(function (c) { out.set(c, at); at += c.length; });
    return out;
  }

  function bytesToBase64(bytes) {
    var chunk = 0x8000, parts = [];
    for (var i = 0; i < bytes.length; i += chunk) {
      parts.push(String.fromCharCode.apply(
        null, bytes.subarray(i, Math.min(i + chunk, bytes.length))));
    }
    return btoa(parts.join(''));
  }

  function base64ToBytes(b64) {
    var bin = atob(String(b64).replace(/^data:[^,]*,/, ''));
    var out = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  var CRC_TABLE = (function () {
    var table = new Uint32Array(256);
    for (var n = 0; n < 256; n++) {
      var c = n;
      for (var k = 0; k < 8; k++) c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
      table[n] = c >>> 0;
    }
    return table;
  }());

  function crc32(bytes) {
    var c = 0xFFFFFFFF;
    for (var i = 0; i < bytes.length; i++) {
      c = CRC_TABLE[(c ^ bytes[i]) & 0xFF] ^ (c >>> 8);
    }
    return (c ^ 0xFFFFFFFF) >>> 0;
  }

  async function deflateRaw(bytes) {
    if (typeof CompressionStream === 'undefined') return null;
    try {
      var stream = new Blob([bytes]).stream()
        .pipeThrough(new CompressionStream('deflate-raw'));
      return new Uint8Array(await new Response(stream).arrayBuffer());
    } catch (e) {
      return null;   /* fall back to stored entries; still a valid archive */
    }
  }

  async function decompress(bytes, format) {
    if (typeof DecompressionStream === 'undefined') {
      throw new Error('This browser cannot decompress .xlsx files. ' +
        'Use a current version of Chrome, Edge, Firefox or Safari.');
    }
    var stream = new Blob([bytes]).stream()
      .pipeThrough(new DecompressionStream(format));
    return new Uint8Array(await new Response(stream).arrayBuffer());
  }

  async function inflateRaw(bytes) {
    return decompress(bytes, 'deflate-raw');
  }

  /* zlib-wrapped deflate: what a PDF /FlateDecode stream carries. A few
   * writers emit the raw stream without the two-byte zlib header, so fall
   * back rather than failing the whole document. */
  async function inflate(bytes) {
    try {
      return await decompress(bytes, 'deflate');
    } catch (e) {
      return inflateRaw(bytes);
    }
  }

  /* ----------------------------------------------------------- ZIP read */

  /* Reads a ZIP container from its central directory, which is the only
   * reliable way: Excel and Word both write streamed entries whose local
   * headers carry zero sizes. Returns {path: Uint8Array}. */
  async function unzip(buffer) {
    var data = buffer instanceof Uint8Array ? buffer : new Uint8Array(buffer);
    var view = new DataView(data.buffer, data.byteOffset, data.byteLength);
    var eocd = -1;
    for (var i = data.length - 22; i >= 0 && i >= data.length - 22 - 65536; i--) {
      if (view.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
    }
    if (eocd < 0) throw new Error('Not a ZIP file (no end-of-directory record).');
    var count = view.getUint16(eocd + 10, true);
    var start = view.getUint32(eocd + 16, true);
    var files = {};
    var at = start;
    for (var n = 0; n < count; n++) {
      if (view.getUint32(at, true) !== 0x02014b50) break;
      var method = view.getUint16(at + 10, true);
      var compressedSize = view.getUint32(at + 20, true);
      var nameLen = view.getUint16(at + 28, true);
      var extraLen = view.getUint16(at + 30, true);
      var commentLen = view.getUint16(at + 32, true);
      var localAt = view.getUint32(at + 42, true);
      var name = new TextDecoder().decode(data.subarray(at + 46, at + 46 + nameLen));
      at += 46 + nameLen + extraLen + commentLen;
      if (/\/$/.test(name)) continue;                       // directory entry
      var lNameLen = view.getUint16(localAt + 26, true);
      var lExtraLen = view.getUint16(localAt + 28, true);
      var dataAt = localAt + 30 + lNameLen + lExtraLen;
      var raw = data.subarray(dataAt, dataAt + compressedSize);
      files[name] = method === 0 ? raw : await inflateRaw(raw);
    }
    return files;
  }

  /* ---------------------------------------------------------- ZIP write */

  /* Writes a ZIP the way Word expects: [Content_Types].xml first and stored,
   * everything else deflated when the browser can. */
  async function zip(entries) {
    var locals = [], central = [], offset = 0;
    for (var i = 0; i < entries.length; i++) {
      var entry = entries[i];
      var name = utf8(entry.name);
      var body = typeof entry.data === 'string' ? utf8(entry.data) : entry.data;
      var crc = crc32(body);
      var stored = entry.store === true;
      var payload = stored ? null : await deflateRaw(body);
      var method = 0;
      if (payload && payload.length < body.length) { method = 8; }
      else { payload = body; method = 0; }

      var local = new Uint8Array(30 + name.length);
      var lv = new DataView(local.buffer);
      lv.setUint32(0, 0x04034b50, true);
      lv.setUint16(4, 20, true);              // version needed
      lv.setUint16(6, 0x0800, true);          // UTF-8 names
      lv.setUint16(8, method, true);
      lv.setUint16(10, 0, true);              // time
      lv.setUint16(12, 0x21, true);           // date (1996-01-01, deterministic)
      lv.setUint32(14, crc, true);
      lv.setUint32(18, payload.length, true);
      lv.setUint32(22, body.length, true);
      lv.setUint16(26, name.length, true);
      lv.setUint16(28, 0, true);
      local.set(name, 30);
      locals.push(local, payload);

      var dir = new Uint8Array(46 + name.length);
      var dv = new DataView(dir.buffer);
      dv.setUint32(0, 0x02014b50, true);
      dv.setUint16(4, 20, true);
      dv.setUint16(6, 20, true);
      dv.setUint16(8, 0x0800, true);
      dv.setUint16(10, method, true);
      dv.setUint16(12, 0, true);
      dv.setUint16(14, 0x21, true);
      dv.setUint32(16, crc, true);
      dv.setUint32(20, payload.length, true);
      dv.setUint32(24, body.length, true);
      dv.setUint16(28, name.length, true);
      dv.setUint32(42, offset, true);
      dir.set(name, 46);
      central.push(dir);

      offset += local.length + payload.length;
    }
    var dirBytes = concatBytes(central);
    var end = new Uint8Array(22);
    var ev = new DataView(end.buffer);
    ev.setUint32(0, 0x06054b50, true);
    ev.setUint16(8, entries.length, true);
    ev.setUint16(10, entries.length, true);
    ev.setUint32(12, dirBytes.length, true);
    ev.setUint32(16, offset, true);
    return concatBytes(locals.concat([dirBytes, end]));
  }

  /* --------------------------------------------------------------- XLSX */

  var A1 = /^([A-Z]+)(\d+)$/;

  function colIndex(letters) {
    var n = 0;
    for (var i = 0; i < letters.length; i++) {
      n = n * 26 + (letters.charCodeAt(i) - 64);
    }
    return n - 1;
  }

  /* Reads an .xlsx into {name, rows} sheets, rows being ragged arrays of
   * numbers, strings, Dates and nulls - the same shape the Python readers see
   * from openpyxl, so the parsers can be written once against it. */
  async function readXlsx(buffer) {
    var files = await unzip(buffer);
    var parser = new DOMParser();
    function doc(path) {
      var bytes = files[path] || files[path.replace(/^\//, '')];
      if (!bytes) return null;
      return parser.parseFromString(new TextDecoder().decode(bytes), 'application/xml');
    }

    var shared = [];
    var sst = doc('xl/sharedStrings.xml');
    if (sst) {
      $$('si', sst.documentElement).forEach(function (si) {
        /* <si> is either a single <t> or a run of <r><t>; drop <rPh> ruby. */
        var text = '';
        $$('t', si).forEach(function (t) {
          if (t.parentNode && t.parentNode.nodeName === 'rPh') return;
          text += t.textContent;
        });
        shared.push(text);
      });
    }

    /* Number formats decide whether a numeric cell is a date. */
    var dateStyles = {};
    var styles = doc('xl/styles.xml');
    if (styles) {
      var customDate = {};
      $$('numFmt', styles.documentElement).forEach(function (f) {
        var code = f.getAttribute('formatCode') || '';
        if (/[dmyhs]/i.test(code.replace(/\[[^\]]*\]/g, '').replace(/"[^"]*"/g, ''))) {
          customDate[f.getAttribute('numFmtId')] = true;
        }
      });
      var cellXfs = $$('cellXfs > xf', styles.documentElement);
      if (!cellXfs.length) {
        var holder = $$('cellXfs', styles.documentElement)[0];
        cellXfs = holder ? $$('xf', holder) : [];
      }
      cellXfs.forEach(function (xf, i) {
        var id = xf.getAttribute('numFmtId');
        var builtin = (id >= 14 && id <= 22) || (id >= 45 && id <= 47);
        if (builtin || customDate[id]) dateStyles[i] = true;
      });
    }

    /* Sheet order and names come from the workbook and its relationships. */
    var rels = {};
    var relsDoc = doc('xl/_rels/workbook.xml.rels');
    if (relsDoc) {
      $$('Relationship', relsDoc.documentElement).forEach(function (r) {
        var target = r.getAttribute('Target') || '';
        if (target.charAt(0) === '/') target = target.slice(1);
        else if (target.indexOf('xl/') !== 0) target = 'xl/' + target.replace(/^\.\//, '');
        rels[r.getAttribute('Id')] = target;
      });
    }
    var book = doc('xl/workbook.xml');
    var sheets = [];
    if (book) {
      $$('sheets > sheet', book.documentElement).forEach(function (s, i) {
        var rid = s.getAttribute('r:id') || s.getAttributeNS(
          'http://schemas.openxmlformats.org/officeDocument/2006/relationships', 'id');
        sheets.push({
          name: s.getAttribute('name') || ('Sheet' + (i + 1)),
          path: rels[rid] || ('xl/worksheets/sheet' + (i + 1) + '.xml'),
          state: s.getAttribute('state') || 'visible',
        });
      });
    }
    if (!sheets.length) {
      Object.keys(files).filter(function (p) {
        return /^xl\/worksheets\/sheet\d+\.xml$/.test(p);
      }).sort().forEach(function (p, i) {
        sheets.push({ name: 'Sheet' + (i + 1), path: p, state: 'visible' });
      });
    }

    return sheets.map(function (sheet) {
      var sd = doc(sheet.path);
      var rows = [];
      if (sd) {
        $$('sheetData > row', sd.documentElement).forEach(function (rowNode) {
          var rowIndex = parseInt(rowNode.getAttribute('r'), 10);
          var cells = [];
          $$('c', rowNode).forEach(function (c) {
            var ref = c.getAttribute('r') || '';
            var m = A1.exec(ref);
            var idx = m ? colIndex(m[1]) : cells.length;
            var type = c.getAttribute('t') || 'n';
            var value = null;
            if (type === 'inlineStr') {
              var isNode = $$('is', c)[0];
              value = isNode ? $$('t', isNode).map(function (t) { return t.textContent; }).join('') : '';
            } else {
              var v = $$('v', c)[0];
              var raw = v ? v.textContent : null;
              if (raw === null || raw === '') value = null;
              else if (type === 's') value = shared[parseInt(raw, 10)];
              else if (type === 'str' || type === 'e') value = raw;
              else if (type === 'b') value = raw === '1';
              else {
                var num = Number(raw);
                var styleIdx = parseInt(c.getAttribute('s') || '0', 10);
                value = (dateStyles[styleIdx] && isFinite(num) && num > 0)
                  ? excelSerialToDate(num) : (isFinite(num) ? num : raw);
              }
            }
            if (typeof value === 'string') {
              value = value.replace(/ /g, ' ');
              if (!value.trim()) value = value.trim() === '' && value !== '' ? null : value;
            }
            while (cells.length < idx) cells.push(null);
            cells[idx] = value;
          });
          while (rows.length < rowIndex - 1) rows.push([]);
          rows[rowIndex - 1] = cells;
        });
      }
      return { name: sheet.name, rows: rows, hidden: sheet.state !== 'visible' };
    }).filter(function (s) { return !s.hidden; });
  }

  /* ------------------------------------------------------------ writing */

  /* A minimal .xlsx writer, enough for the BoQ and template downloads.
   * sheets: [{name, rows: [[cell, ...], ...]}] */
  async function writeXlsx(sheets) {
    var strings = [], stringIndex = {};
    function sharedIndex(text) {
      if (!(text in stringIndex)) {
        stringIndex[text] = strings.length;
        strings.push(text);
      }
      return stringIndex[text];
    }
    function colName(i) {
      var s = '';
      i += 1;
      while (i > 0) {
        var rem = (i - 1) % 26;
        s = String.fromCharCode(65 + rem) + s;
        i = Math.floor((i - 1) / 26);
      }
      return s;
    }
    /* A cell is a bare value, or {v, bold, flag} when it needs a style. The
     * flag style is the amber fill the review workbook uses to mark a value a
     * human still has to check - the same signal openpyxl paints server side. */
    var STYLE_INDEX = { plain: 0, bold: 1, flag: 2, boldflag: 3 };
    function styleFor(cell, rowIndex) {
      var bold = rowIndex === 0, flag = false;
      if (cell && typeof cell === 'object' && !(cell instanceof Date)) {
        if (cell.bold !== undefined) bold = !!cell.bold;
        flag = !!cell.flag;
      }
      var key = (bold ? 'bold' : '') + (flag ? 'flag' : '');
      return STYLE_INDEX[key || 'plain'];
    }
    var sheetXml = sheets.map(function (sheet) {
      var body = (sheet.rows || []).map(function (row, r) {
        var cells = (row || []).map(function (cell, c) {
          var value = cell && typeof cell === 'object' && !(cell instanceof Date)
            ? cell.v : cell;
          var index = styleFor(cell, r);
          if (value === null || value === undefined || value === '') {
            /* an empty but flagged cell still has to carry its colour: a blank
             * where a number belongs is exactly the thing to review */
            if (!index) return '';
            return '<c r="' + colName(c) + (r + 1) + '" s="' + index + '"/>';
          }
          var ref = colName(c) + (r + 1);
          var style = index ? ' s="' + index + '"' : '';
          if (typeof value === 'number' && isFinite(value)) {
            return '<c r="' + ref + '"' + style + '><v>' + value + '</v></c>';
          }
          return '<c r="' + ref + '"' + style + ' t="s"><v>' +
            sharedIndex(String(value)) + '</v></c>';
        }).join('');
        return cells ? '<row r="' + (r + 1) + '">' + cells + '</row>' : '';
      }).join('');
      var widths = (sheet.widths || []).map(function (w, i) {
        return w ? '<col min="' + (i + 1) + '" max="' + (i + 1) +
          '" width="' + w + '" customWidth="1"/>' : '';
      }).join('');
      return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' +
        (widths ? '<cols>' + widths + '</cols>' : '') +
        '<sheetData>' + body + '</sheetData></worksheet>';
    });

    var sst = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="' +
      strings.length + '" uniqueCount="' + strings.length + '">' +
      strings.map(function (s) {
        return '<si><t xml:space="preserve">' + escapeXml(s) + '</t></si>';
      }).join('') + '</sst>';

    var entries = [
      { name: '[Content_Types].xml', store: true, data:
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
        '<Default Extension="xml" ContentType="application/xml"/>' +
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>' +
        sheets.map(function (s, i) {
          return '<Override PartName="/xl/worksheets/sheet' + (i + 1) +
            '.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>';
        }).join('') +
        '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>' +
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>' +
        '</Types>' },
      { name: '_rels/.rels', data:
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>' +
        '</Relationships>' },
      { name: 'xl/workbook.xml', data:
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" ' +
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' +
        sheets.map(function (s, i) {
          return '<sheet name="' + escapeXml(String(s.name).slice(0, 31).replace(/[\\\/\?\*\[\]:]/g, '-')) +
            '" sheetId="' + (i + 1) + '" r:id="rId' + (i + 1) + '"/>';
        }).join('') + '</sheets></workbook>' },
      { name: 'xl/_rels/workbook.xml.rels', data:
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
        sheets.map(function (s, i) {
          return '<Relationship Id="rId' + (i + 1) +
            '" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet' +
            (i + 1) + '.xml"/>';
        }).join('') +
        '<Relationship Id="rId' + (sheets.length + 1) +
        '" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>' +
        '<Relationship Id="rId' + (sheets.length + 2) +
        '" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>' +
        '</Relationships>' },
      { name: 'xl/styles.xml', data:
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' +
        '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>' +
        '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>' +
        '<fills count="3"><fill><patternFill patternType="none"/></fill>' +
        '<fill><patternFill patternType="gray125"/></fill>' +
        '<fill><patternFill patternType="solid"><fgColor rgb="FFFFE08A"/>' +
        '<bgColor indexed="64"/></patternFill></fill></fills>' +
        '<borders count="1"><border/></borders>' +
        '<cellStyleXfs count="1"><xf/></cellStyleXfs>' +
        '<cellXfs count="4"><xf xfId="0"/>' +
        '<xf fontId="1" applyFont="1" xfId="0"/>' +
        '<xf fillId="2" applyFill="1" xfId="0"/>' +
        '<xf fontId="1" fillId="2" applyFont="1" applyFill="1" xfId="0"/></cellXfs>' +
        '</styleSheet>' },
      { name: 'xl/sharedStrings.xml', data: sst },
    ].concat(sheetXml.map(function (xml, i) {
      return { name: 'xl/worksheets/sheet' + (i + 1) + '.xml', data: xml };
    }));

    return zip(entries);
  }

  /* ---------------------------------------------------------------- CSV */

  function parseCsv(text, options) {
    var opts = options || {};
    var rows = [], row = [], field = '', quoted = false, i = 0;
    var src = String(text).replace(/^﻿/, '');
    while (i < src.length) {
      var ch = src[i];
      if (quoted) {
        if (ch === '"') {
          if (src[i + 1] === '"') { field += '"'; i += 2; continue; }
          quoted = false; i++; continue;
        }
        field += ch; i++; continue;
      }
      if (ch === '"') { quoted = true; i++; continue; }
      if (ch === ',') { row.push(field); field = ''; i++; continue; }
      if (ch === '\r') { i++; continue; }
      if (ch === '\n') { row.push(field); rows.push(row); row = []; field = ''; i++; continue; }
      field += ch; i++;
    }
    if (field !== '' || row.length) { row.push(field); rows.push(row); }
    rows = rows.filter(function (r) {
      return r.length > 1 || (r[0] !== undefined && r[0] !== '');
    });
    if (opts.raw) return rows;
    var header = rows.shift() || [];
    return rows.map(function (r) {
      var obj = {};
      header.forEach(function (h, j) { obj[h.trim()] = r[j] === undefined ? '' : r[j]; });
      return obj;
    });
  }

  /* ---------------------------------------------------------------- YAML
   *
   * Enough of YAML to read a project file the Streamlit app saved: block
   * mappings, block sequences, quoted and plain scalars, and the line folding
   * PyYAML applies to long plain scalars. Flow style, anchors, tags, multiple
   * documents and block scalars are not supported and raise, because a reader
   * that half-understands a file is worse than one that says it cannot read it
   * - the caller reports the file as skipped rather than importing nonsense.
   */
  function parseYaml(text) {
    var lines = String(text).replace(/\r\n?/g, '\n').split('\n');
    var clean = [];
    lines.forEach(function (raw) {
      if (/^\s*#/.test(raw) || !raw.trim()) return;
      if (/^(---|\.\.\.)\s*$/.test(raw)) return;
      clean.push(raw);
    });
    var at = 0;

    function indentOf(line) { return /^ */.exec(line)[0].length; }

    function scalar(token) {
      var s = String(token).trim();
      if (s === '' || s === '~' || s === 'null' || s === 'Null' || s === 'NULL') return null;
      if (s === 'true' || s === 'True') return true;
      if (s === 'false' || s === 'False') return false;
      if (s.charAt(0) === '"' && s.charAt(s.length - 1) === '"' && s.length > 1) {
        return s.slice(1, -1)
          .replace(/\\n/g, '\n').replace(/\\t/g, '\t').replace(/\\"/g, '"')
          .replace(/\\\\/g, '\\');
      }
      if (s.charAt(0) === "'" && s.charAt(s.length - 1) === "'" && s.length > 1) {
        return s.slice(1, -1).replace(/''/g, "'");
      }
      if (s.charAt(0) === '[' || s.charAt(0) === '{' || s.charAt(0) === '&' ||
          s.charAt(0) === '*' || s.charAt(0) === '!' || s.charAt(0) === '|' ||
          s.charAt(0) === '>') {
        throw new Error('unsupported YAML construct: ' + s.slice(0, 12));
      }
      if (/^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/.test(s)) return Number(s);
      return s;
    }

    /* PyYAML folds a long plain scalar across lines. Once a key has a value on
     * its own line, anything indented deeper belongs to that value and joins
     * with a single space - there is nothing else a deeper line could be. */
    function foldedScalar(first, indent) {
      var parts = [first];
      while (at < clean.length && indentOf(clean[at]) > indent) {
        parts.push(clean[at].trim());
        at += 1;
      }
      return parts.join(' ');
    }

    function parseBlock(indent) {
      var line = clean[at];
      if (/^\s*-\s*/.test(line)) return parseSequence(indent);
      return parseMapping(indent);
    }

    function parseSequence(indent) {
      var out = [];
      while (at < clean.length) {
        var line = clean[at];
        var here = indentOf(line);
        if (here < indent || !/^\s*-(\s|$)/.test(line)) break;
        if (here > indent) throw new Error('inconsistent YAML indentation');
        var rest = line.slice(here + 1).replace(/^ /, '');
        at += 1;
        if (!rest.trim()) {
          out.push(at < clean.length && indentOf(clean[at]) > here
            ? parseBlock(indentOf(clean[at])) : null);
          continue;
        }
        if (/^[^:]+:(\s|$)/.test(rest)) {
          /* "- key: value" starts a mapping whose keys align after the dash */
          clean[at - 1] = new Array(here + 3).join(' ') + rest;
          at -= 1;
          out.push(parseMapping(here + 2));
          continue;
        }
        out.push(scalar(foldedScalar(rest, here)));
      }
      return out;
    }

    function parseMapping(indent) {
      var out = {};
      while (at < clean.length) {
        var line = clean[at];
        var here = indentOf(line);
        if (here < indent) break;
        if (here > indent) throw new Error('inconsistent YAML indentation');
        var body = line.slice(here);
        var split = /^((?:"[^"]*")|(?:'[^']*')|(?:[^:]+)):(?:\s+(.*))?$/.exec(body);
        if (!split) throw new Error('unreadable YAML line: ' + body.slice(0, 40));
        var key = String(scalar(split[1]));
        var rest = split[2] === undefined ? '' : split[2];
        at += 1;
        if (rest.trim() === '') {
          if (at < clean.length && indentOf(clean[at]) > here) {
            out[key] = parseBlock(indentOf(clean[at]));
          } else if (at < clean.length && indentOf(clean[at]) === here &&
                     /^\s*-(\s|$)/.test(clean[at])) {
            out[key] = parseSequence(here);
          } else {
            out[key] = null;
          }
          continue;
        }
        out[key] = scalar(foldedScalar(rest, here));
      }
      return out;
    }

    if (!clean.length) return null;
    var value = parseBlock(indentOf(clean[0]));
    if (at < clean.length) throw new Error('trailing YAML content');
    return value;
  }

  function toCsv(rows, header) {
    var cols = header;
    if (!cols) {
      cols = [];
      rows.forEach(function (r) {
        Object.keys(r).forEach(function (k) {
          if (cols.indexOf(k) < 0) cols.push(k);
        });
      });
    }
    function cell(v) {
      if (v === null || v === undefined) return '';
      var s = String(v);
      return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
    }
    var lines = [cols.map(cell).join(',')];
    rows.forEach(function (r) {
      lines.push(cols.map(function (c) {
        return cell(Array.isArray(r) ? r[cols.indexOf(c)] : r[c]);
      }).join(','));
    });
    return lines.join('\r\n') + '\r\n';
  }

  /* --------------------------------------------------------- file in/out */

  function download(filename, data, mime) {
    var blob = data instanceof Blob ? data
      : new Blob([data], { type: mime || 'application/octet-stream' });
    var url = URL.createObjectURL(blob);
    var a = el('a', { href: url, download: filename });
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(url); }, 2000);
  }

  function readFile(file, as) {
    return new Promise(function (resolve, reject) {
      var reader = new FileReader();
      reader.onerror = function () { reject(reader.error || new Error('Could not read ' + file.name)); };
      reader.onload = function () { resolve(reader.result); };
      if (as === 'text') reader.readAsText(file);
      else if (as === 'dataUrl') reader.readAsDataURL(file);
      else reader.readAsArrayBuffer(file);
    });
  }

  function pickFile(accept, multiple) {
    return new Promise(function (resolve) {
      var input = el('input', {
        type: 'file', accept: accept || '', multiple: !!multiple,
        style: { position: 'fixed', left: '-9999px' },
      });
      input.addEventListener('change', function () {
        var files = Array.prototype.slice.call(input.files || []);
        document.body.removeChild(input);
        resolve(multiple ? files : files[0] || null);
      });
      document.body.appendChild(input);
      input.click();
    });
  }

  /* ---------------------------------------------------------- the store */

  /* One observable object holding the whole working session. Pages read from
   * it, write to it, and re-render on change. It round-trips to a .gwt project
   * file and is mirrored into localStorage so a refresh never loses fieldwork. */
  function createStore(initial, options) {
    var opts = options || {};
    var state = JSON.parse(JSON.stringify(initial || {}));
    var listeners = [];
    var saveTimer = null;

    function get(path, fallback) {
      if (!path) return state;
      var node = state;
      var parts = String(path).split('.');
      for (var i = 0; i < parts.length; i++) {
        if (node === null || node === undefined) return fallback;
        node = node[parts[i]];
      }
      return node === undefined ? fallback : node;
    }

    function set(path, value) {
      var parts = String(path).split('.');
      var node = state;
      for (var i = 0; i < parts.length - 1; i++) {
        if (typeof node[parts[i]] !== 'object' || node[parts[i]] === null) {
          node[parts[i]] = {};
        }
        node = node[parts[i]];
      }
      var last = parts[parts.length - 1];
      if (node[last] === value) return value;
      node[last] = value;
      emit(path);
      return value;
    }

    function patch(values) {
      Object.keys(values).forEach(function (k) {
        var parts = k.split('.');
        var node = state;
        for (var i = 0; i < parts.length - 1; i++) {
          if (typeof node[parts[i]] !== 'object' || node[parts[i]] === null) {
            node[parts[i]] = {};
          }
          node = node[parts[i]];
        }
        node[parts[parts.length - 1]] = values[k];
      });
      emit('*');
    }

    function remove(path) {
      var parts = String(path).split('.');
      var node = state;
      for (var i = 0; i < parts.length - 1; i++) {
        node = node[parts[i]];
        if (!node) return;
      }
      delete node[parts[parts.length - 1]];
      emit(path);
    }

    function replace(next) {
      state = JSON.parse(JSON.stringify(next || {}));
      emit('*');
    }

    function subscribe(fn) {
      listeners.push(fn);
      return function () {
        var i = listeners.indexOf(fn);
        if (i >= 0) listeners.splice(i, 1);
      };
    }

    function emit(path) {
      listeners.forEach(function (fn) {
        try { fn(path, state); } catch (e) { console.error(e); }
      });
      if (opts.persistKey) {
        clearTimeout(saveTimer);
        saveTimer = setTimeout(persist, 400);
      }
    }

    function persist() {
      if (!opts.persistKey) return;
      try {
        localStorage.setItem(opts.persistKey, JSON.stringify(state));
      } catch (e) {
        /* Quota is finite and photos are large; drop the mirror rather than
         * interrupting the user, the project file remains the real record. */
        try { localStorage.removeItem(opts.persistKey); } catch (e2) { /* ignore */ }
      }
    }

    function restore() {
      if (!opts.persistKey) return false;
      try {
        var raw = localStorage.getItem(opts.persistKey);
        if (!raw) return false;
        var saved = JSON.parse(raw);
        if (!saved || typeof saved !== 'object') return false;
        state = saved;
        return true;
      } catch (e) { return false; }
    }

    function forget() {
      if (opts.persistKey) {
        try { localStorage.removeItem(opts.persistKey); } catch (e) { /* ignore */ }
      }
    }

    return {
      get: get, set: set, patch: patch, remove: remove, replace: replace,
      subscribe: subscribe, persist: persist, restore: restore, forget: forget,
      emit: emit,
      get state() { return state; },
    };
  }

  /* ------------------------------------------------------------ UI bits */

  function card(title, children, options) {
    var opts = options || {};
    var head = title ? el('div.card-head', [
      el('h3.card-title', title),
      opts.actions ? el('div.card-actions', opts.actions) : null,
    ]) : null;
    return el('section.card' + (opts.className ? '.' + opts.className : ''), [
      head,
      opts.note ? el('p.card-note', opts.note) : null,
      el('div.card-body', children),
    ]);
  }

  function field(label, control, hint) {
    return el('label.field', [
      el('span.field-label', label),
      control,
      hint ? el('span.field-hint', hint) : null,
    ]);
  }

  function numberInput(value, onChange, attrs) {
    var input = el('input.input', Object.assign({
      type: 'number', value: isNum(value) ? value : '',
    }, attrs || {}));
    input.addEventListener('change', function () {
      onChange(parseNum(input.value));
    });
    return input;
  }

  function textInput(value, onChange, attrs) {
    var input = el('input.input', Object.assign({
      type: 'text', value: value === null || value === undefined ? '' : value,
    }, attrs || {}));
    input.addEventListener('change', function () { onChange(input.value); });
    return input;
  }

  function selectInput(value, choices, onChange, attrs) {
    var select = el('select.input', attrs || {},
      choices.map(function (c) {
        var v = typeof c === 'object' ? c.value : c;
        var lab = typeof c === 'object' ? c.label : c;
        return el('option', { value: v, selected: String(v) === String(value) }, lab);
      }));
    select.addEventListener('change', function () { onChange(select.value); });
    return select;
  }

  function checkboxInput(value, label, onChange) {
    var input = el('input', { type: 'checkbox', checked: !!value });
    input.addEventListener('change', function () { onChange(input.checked); });
    return el('label.check', [input, el('span', label)]);
  }

  function button(label, onClick, options) {
    var opts = options || {};
    return el('button.btn' + (opts.variant ? '.btn-' + opts.variant : ''), {
      type: 'button', onclick: onClick, disabled: !!opts.disabled,
      title: opts.title || '',
    }, label);
  }

  function badge(text, tone) {
    return el('span.badge' + (tone ? '.badge-' + tone : ''), text);
  }

  /* columns: [{key, label, align, format}] */
  function table(columns, rows, options) {
    var opts = options || {};
    var head = el('thead', el('tr', columns.map(function (c) {
      return el('th', { class: c.align === 'right' ? 'right' : '' }, c.label);
    })));
    var body = el('tbody', rows.map(function (row, i) {
      return el('tr', { class: opts.rowClass ? opts.rowClass(row, i) : '' },
        columns.map(function (c) {
          var raw = typeof c.key === 'function' ? c.key(row, i) : row[c.key];
          var content = c.format ? c.format(raw, row, i) : raw;
          if (content === null || content === undefined || content === '') {
            content = '–';
          }
          return el('td', { class: c.align === 'right' ? 'right' : '' }, content);
        }));
    }));
    var tbl = el('table.data', [head, body]);
    if (!rows.length && opts.empty !== false) {
      body.appendChild(el('tr', el('td', { colspan: columns.length, class: 'empty' },
        opts.emptyText || 'Nothing to show yet.')));
    }
    return el('div.table-wrap', tbl);
  }

  /* An editable grid, used for rate overrides, committee members and manual
   * data entry. columns: [{key, label, type, choices, width}] */
  function editableTable(columns, rows, onChange, options) {
    var opts = options || {};
    var data = rows.map(function (r) { return Object.assign({}, r); });

    function fire() { onChange(data.map(function (r) { return Object.assign({}, r); })); }

    function render() {
      var head = el('thead', el('tr', columns.map(function (c) {
        return el('th', { style: c.width ? { width: c.width } : null }, c.label);
      }).concat(opts.fixedRows ? [] : [el('th.right', '')])));
      var body = el('tbody', data.map(function (row, i) {
        var cells = columns.map(function (c) {
          var control;
          if (c.type === 'number') {
            control = numberInput(row[c.key], function (v) { row[c.key] = v; fire(); },
              { step: c.step || 'any', class: 'input cell' });
          } else if (c.type === 'select') {
            control = selectInput(row[c.key], c.choices, function (v) {
              row[c.key] = v; fire();
            }, { class: 'input cell' });
          } else if (c.type === 'readonly') {
            control = el('span.cell-static', row[c.key] === null ||
              row[c.key] === undefined ? '–' : String(row[c.key]));
          } else {
            control = textInput(row[c.key], function (v) { row[c.key] = v; fire(); },
              { class: 'input cell' });
          }
          return el('td', control);
        });
        if (!opts.fixedRows) {
          cells.push(el('td.right', button('×', function () {
            data.splice(i, 1); fire(); render();
          }, { variant: 'ghost', title: 'Remove this row' })));
        }
        return el('tr', cells);
      }));
      var wrap = el('div.table-wrap', el('table.data.editable', [head, body]));
      var foot = opts.fixedRows ? null : el('div.table-foot', [
        button(opts.addLabel || '+ Add row', function () {
          var blank = {};
          columns.forEach(function (c) { blank[c.key] = c.type === 'number' ? null : ''; });
          data.push(Object.assign(blank, opts.blank || {}));
          fire(); render();
        }, { variant: 'ghost' }),
      ]);
      clear(host);
      append(host, [wrap, foot]);
    }

    var host = el('div.editable-host');
    render();
    return host;
  }

  var toastHost = null;
  function toast(message, tone, timeout) {
    if (!toastHost) {
      toastHost = el('div.toast-host');
      document.body.appendChild(toastHost);
    }
    var node = el('div.toast' + (tone ? '.toast-' + tone : ''), message);
    toastHost.appendChild(node);
    setTimeout(function () {
      node.classList.add('leaving');
      setTimeout(function () {
        if (node.parentNode) node.parentNode.removeChild(node);
      }, 300);
    }, timeout || 4200);
    return node;
  }

  function modal(title, body, actions) {
    var overlay = el('div.modal-overlay');
    function close() {
      if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
      document.removeEventListener('keydown', onKey);
    }
    function onKey(e) { if (e.key === 'Escape') close(); }
    var box = el('div.modal', [
      el('div.modal-head', [
        el('h3', title),
        button('×', close, { variant: 'ghost' }),
      ]),
      el('div.modal-body', body),
      el('div.modal-foot', (actions || []).concat([
        button('Close', close, { variant: 'ghost' }),
      ])),
    ]);
    overlay.appendChild(box);
    overlay.addEventListener('click', function (e) {
      if (e.target === overlay) close();
    });
    document.addEventListener('keydown', onKey);
    document.body.appendChild(overlay);
    return { close: close, node: box };
  }

  /* The data checks produce {level, message, ...}; render them the same way
   * everywhere so a warning never hides at the bottom of a page. */
  function checkList(checks, options) {
    var opts = options || {};
    if (!checks || !checks.length) {
      return el('p.checks-clear', opts.clearText || 'All checks passed.');
    }
    var order = { error: 0, warning: 1, info: 2 };
    var sorted = checks.slice().sort(function (a, b) {
      return (order[a.level] === undefined ? 3 : order[a.level]) -
             (order[b.level] === undefined ? 3 : order[b.level]);
    });
    return el('ul.checks', sorted.map(function (c) {
      return el('li.check.check-' + (c.level || 'info'), [
        badge(c.level === 'error' ? 'Error' : c.level === 'warning' ? 'Check' : 'Note',
          c.level || 'info'),
        el('span.check-text', c.message || String(c)),
        c.detail ? el('span.check-detail', c.detail) : null,
      ]);
    }));
  }

  function stat(label, value, note) {
    return el('div.stat', [
      el('span.stat-label', label),
      el('span.stat-value', value),
      note ? el('span.stat-note', note) : null,
    ]);
  }

  function statRow(items) {
    return el('div.stat-row', items);
  }

  function empty(message, action) {
    return el('div.empty-state', [el('p', message), action || null]);
  }

  function section(title, children) {
    return el('div.section', [title ? el('h4.section-title', title) : null, children]);
  }

  function debounce(fn, wait) {
    var timer = null;
    return function () {
      var args = arguments, self = this;
      clearTimeout(timer);
      timer = setTimeout(function () { fn.apply(self, args); }, wait || 200);
    };
  }

  /* Long computations (the VES inversion) must not freeze the page before the
   * spinner has had a chance to paint. */
  function nextFrame() {
    return new Promise(function (resolve) {
      requestAnimationFrame(function () { setTimeout(resolve, 0); });
    });
  }

  async function withBusy(node, label, work) {
    var overlay = el('div.busy', [el('span.spinner'), el('span', label || 'Working…')]);
    node.appendChild(overlay);
    await nextFrame();
    try {
      return await work();
    } finally {
      if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
    }
  }

  Object.assign(S, {
    $: $, $$: $$, el: el, svgEl: svgEl, append: append, clear: clear,
    parseNum: parseNum, isNum: isNum, fmt: fmt, sig: sig, thousands: thousands,
    money: money, clamp: clamp, round: round, mean: mean, median: median,
    sum: sum, range: range, linspace: linspace, logspace: logspace,
    parseDate: parseDate, formatDate: formatDate, formatDateLong: formatDateLong,
    excelSerialToDate: excelSerialToDate, today: today,
    slug: slug, titleCase: titleCase, escapeHtml: escapeHtml, escapeXml: escapeXml,
    plural: plural, joinList: joinList, normaliseKey: normaliseKey,
    utf8: utf8, concatBytes: concatBytes, bytesToBase64: bytesToBase64,
    base64ToBytes: base64ToBytes, crc32: crc32, zip: zip, unzip: unzip,
    inflate: inflate, inflateRaw: inflateRaw,
    readXlsx: readXlsx, writeXlsx: writeXlsx, parseCsv: parseCsv, toCsv: toCsv,
    parseYaml: parseYaml,
    download: download, readFile: readFile, pickFile: pickFile,
    createStore: createStore,
    card: card, field: field, numberInput: numberInput, textInput: textInput,
    selectInput: selectInput, checkboxInput: checkboxInput, button: button,
    badge: badge, table: table, editableTable: editableTable, toast: toast,
    modal: modal, checkList: checkList, stat: stat, statRow: statRow,
    empty: empty, section: section, debounce: debounce, nextFrame: nextFrame,
    withBusy: withBusy,
  });
}(typeof window !== 'undefined' ? window : globalThis));

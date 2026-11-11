
  /* ================================================== documents verified
   * groundwater/verification.py (PLAN.md step 8.1). Every document either
   * engine writes carries a manifest, customXml/groundwater-manifest.xml:
   * what it is, the engine, the calibration set in force, its readiness, the
   * SHA-256 of each evidence file it was issued from and of every other part
   * of the package. The SHA-256 of the manifest is the document's hash, which
   * the issue records in the project file and the asset record hold. The
   * code on the cover and in every footer is a short form of the code
   * digest: the manifest written without the code and without the parts that
   * carry it (the footers and the QR symbol, listed apart as carriers), so a
   * copy whose text is changed and whose manifest is brought into line no
   * longer gives its own code. The two engines write different parts, but
   * the same manifest for the same facts and parts, read a package by the
   * same rules and say the same four things of it. */

  var MANIFEST_PART = 'customXml/groundwater-manifest.xml';
  var MANIFEST_NS = 'urn:groundwater-toolkit:manifest';
  var MANIFEST_FORMAT = 1;
  var MANIFEST_REL_ID = 'rIdGroundwaterManifest';
  var MANIFEST_REL_TYPE = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXml';
  var DOCUMENT_RELS = 'word/_rels/document.xml.rels';
  var CONTENT_TYPES = '[Content_Types].xml';
  var XML_DEFAULT = '<Default Extension="xml" ContentType="application/xml"/>';
  /* the engine a manifest names, as the inversion cache names it, with the
   * toolkit's version (verification.ENGINE is the Python engine's) */
  var DOCUMENT_ENGINE = 'gwt-core';
  var READINESS_STATES = ['ready', 'ready_with_overrides', 'not_ready', 'not_assessed'];
  /* the kinds of document about the borehole itself, whose issue records go
   * into its asset record too: those with a certification gate */
  var BOREHOLE_KINDS = Object.keys(READINESS_REPORTS);
  var VERDICTS = ['verified', 'unconfirmed', 'changed', 'not_issued', 'altered_manifest',
    'damaged_manifest', 'no_manifest', 'unreadable'];
  /* a part larger than this, or a package larger in all, is not read */
  var MAX_PART_BYTES = 128 * 1024 * 1024;
  var MAX_PACKAGE_BYTES = 512 * 1024 * 1024;
  var HEX64_RE = /^[0-9a-f]{64}$/;
  var DOCUMENT_CODE_RE = /^[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]$/;
  /* what XML 1.0 cannot carry, dropped from a value; with the u flag a lone
   * surrogate matches and a pair does not, as in a Python str */
  var UNWRITABLE_CLASS = '\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f\\ufffe\\uffff\\u{d800}-\\u{dfff}';
  var UNWRITABLE_RE = new RegExp('[' + UNWRITABLE_CLASS + ']', 'gu');
  var CODE_BLANKS_RE = new RegExp('[' + TRIMMED + '_\\-]+', 'g');
  var MANIFEST_ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;',
    '\t': '&#9;', '\n': '&#10;', '\r': '&#13;' };
  var MANIFEST_UNESCAPES = { '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"',
    '&#9;': '\t', '&#10;': '\n', '&#13;': '\r' };
  var MANIFEST_HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>';
  var MANIFEST_OPEN = '<manifest xmlns="' + MANIFEST_NS + '" format="' + MANIFEST_FORMAT + '">';
  var MANIFEST_V = '([^"<>]*)';
  var MANIFEST_LINES = {
    document: new RegExp('^<document kind="' + MANIFEST_V + '" title="' + MANIFEST_V + '" issued="' +
      MANIFEST_V + '" code="' + MANIFEST_V + '"/>$'),
    engine: new RegExp('^<engine name="' + MANIFEST_V + '" version="' + MANIFEST_V + '"/>$'),
    calibration: new RegExp('^<calibration name="' + MANIFEST_V + '" sha256="' + MANIFEST_V + '"/>$'),
    readiness: new RegExp('^<readiness state="' + MANIFEST_V + '">$'),
    item: new RegExp('^<item state="' + MANIFEST_V + '" title="' + MANIFEST_V + '" by="' + MANIFEST_V +
      '" reason="' + MANIFEST_V + '"/>$'),
    file: new RegExp('^<file what="' + MANIFEST_V + '" name="' + MANIFEST_V + '" sha256="' +
      MANIFEST_V + '"/>$'),
    part: new RegExp('^<part name="' + MANIFEST_V + '" sha256="' + MANIFEST_V + '"/>$'),
  };
  var RECORD_KEYS = ['code', 'sha256', 'kind', 'title', 'issued_on', 'readiness'];

  /* a field of the manifest: text with what XML cannot carry dropped, trimmed
   * as both engines trim; anything but text is blank */
  function manifestText(value) {
    return typeof value === 'string' ? trimField(value.replace(UNWRITABLE_RE, '')) : '';
  }

  function utf8Encode(text) {
    return new TextEncoder().encode(text);
  }

  /** verification.document_code: the short code of a code digest, its first
   * 40 bits as eight Crockford base-32 characters in two groups and an ISO
   * 7064 MOD 37,36 check character, as the asset identifier has.
   * @param {string} digest a SHA-256 as hex
   * @returns {string} */
  function documentCode(digest) {
    var body = '';
    [0, 5].forEach(function (start) {
      var value = parseInt(digest.slice(start, start + 5), 16);
      [15, 10, 5, 0].forEach(function (shift) {
        body += CROCKFORD.charAt((value >>> shift) & 31);
      });
    });
    return body.slice(0, 4) + '-' + body.slice(4) + '-' + checkCharacter(body);
  }

  /** verification.parse_document_code: a typed or scanned code as the
   * toolkit writes it, or null. Case, blanks, missing hyphens, the word
   * DOCUMENT the QR symbol leads with and the four Crockford confusions in
   * the body are forgiven; a wrong check character, and anything but ASCII,
   * is not.
   * @param {*} text
   * @returns {string|null} */
  function parseDocumentCode(text) {
    var raw = String(text === null || text === undefined ? '' : text).replace(CODE_BLANKS_RE, '');
    if (/[^\x20-\x7e]/.test(raw)) return null;
    raw = raw.toUpperCase();
    if (raw.indexOf('DOCUMENT') === 0) raw = raw.slice('DOCUMENT'.length);
    if (raw.length !== 9) return null;
    var body = raw.slice(0, 8).split('').map(function (ch) {
      return own(CROCKFORD_FOLD, ch) ? CROCKFORD_FOLD[ch] : ch;
    }).join('');
    for (var i = 0; i < body.length; i++) {
      if (CROCKFORD.indexOf(body.charAt(i)) < 0) return null;
    }
    if (checkCharacter(body) !== raw.charAt(8)) return null;
    return body.slice(0, 4) + '-' + body.slice(4) + '-' + raw.charAt(8);
  }

  function readinessStateOf(items) {
    if (items.some(function (item) { return item.state === 'unmet'; })) return 'not_ready';
    return items.length ? 'ready_with_overrides' : 'ready';
  }

  /** verification.readiness_facts: what a manifest records of a readiness,
   * its state and each requirement that held the document back, in the
   * gate's order; null is a document no gate was run for.
   * @param {Rec|null} [readiness] what assessReadiness returns
   * @returns {{state: string, items: Rec[]}} */
  function readinessFacts(readiness) {
    if (!readiness) return { state: 'not_assessed', items: [] };
    var items = [];
    (readiness.requirements || []).forEach(function (req) {
      if (req.state === 'unmet') {
        items.push({ state: 'unmet', title: manifestText(req.title), by: '', reason: '' });
      } else if (req.state === 'overridden') {
        items.push({ state: 'overridden', title: manifestText(req.title),
          by: manifestText(req.override_by), reason: manifestText(req.override_reason) });
      }
    });
    return { state: readinessStateOf(items), items: items };
  }

  /** verification.evidence_entry: one evidence file as a manifest lists it.
   * @param {string} what
   * @param {string} name
   * @param {Uint8Array} bytes
   * @returns {{what: string, name: string, sha256: string}} */
  function evidenceEntry(what, name, bytes) {
    return { what: manifestText(what), name: manifestText(name), sha256: sha256Hex(bytes) };
  }

  /** verification.calibration_facts: the calibration set in force as a
   * manifest names it, by its name and the SHA-256 of its calibration.yaml;
   * null is the provisional default.
   * @param {Rec|null} [set]
   * @returns {{name: string, sha256: string}} */
  function calibrationFacts(set) {
    var s = cleanSet(set || defaultSet());
    return { name: setName(s), sha256: sha256Hex(setYaml(s)) };
  }

  function evidenceCompare(a, b) {
    return codePointCompare(a.what, b.what) || codePointCompare(a.name, b.name) ||
      codePointCompare(a.sha256, b.sha256);
  }

  /** verification.manifest_facts: the facts a manifest records, cleaned and
   * in order. An issue date that is not a day, an evidence file with no
   * SHA-256 and a calibration named without a hash throw.
   * @param {string} kind
   * @param {string} title
   * @param {string} [issuedOn] an ISO day, or blank
   * @param {string[]} [engine] [name, version]
   * @param {{name: string, sha256: string}|null} [calibration] calibrationFacts, or null: not stated
   * @param {Rec|null} [readiness] as readinessFacts takes it, or its result
   * @param {Rec[]} [evidence] evidenceEntry's
   * @returns {Rec} */
  function manifestFacts(kind, title, issuedOn, engine, calibration, readiness, evidence) {
    var issued = manifestText(issuedOn === undefined ? '' : issuedOn);
    if (issued && isoDay(issued) === null) {
      throw new Error(phrase('verification.bad_date', { date: issued }));
    }
    /** @type {Rec[]} */
    var files = [];
    (evidence || []).forEach(function (entry) {
      var digest = manifestText(entry.sha256);
      if (!HEX64_RE.test(digest)) {
        throw new Error(phrase('verification.bad_hash', { name: manifestText(entry.name) }));
      }
      var item = { what: manifestText(entry.what), name: manifestText(entry.name), sha256: digest };
      if (!files.some(function (f) { return evidenceCompare(f, item) === 0; })) files.push(item);
    });
    files.sort(evidenceCompare);
    var cal = { name: '', sha256: '' };
    if (calibration) {
      cal = { name: manifestText(calibration.name), sha256: manifestText(calibration.sha256) };
      if (!cal.name || !HEX64_RE.test(cal.sha256)) throw new Error(phrase('verification.bad_calibration'));
    }
    var ready;
    if (readiness && Object.keys(readiness).sort().join(',') === 'items,state') {
      /* already the manifest's shape, as read back from one: cleaned as it
       * would have been written */
      ready = { state: manifestText(readiness.state),
        items: (readiness.items || []).map(function (item) {
          return { state: manifestText(item.state), title: manifestText(item.title),
            by: manifestText(item.by), reason: manifestText(item.reason) };
        }) };
    } else {
      ready = readinessFacts(readiness);
    }
    var eng = engine || ['', ''];
    return {
      document: { kind: manifestText(kind), title: manifestText(title), issued_on: issued },
      engine: { name: manifestText(eng[0]), version: manifestText(eng[1]) },
      calibration: cal,
      readiness: ready,
      evidence: files,
    };
  }

  function manifestAttr(value) {
    return value.replace(/[&<>"\t\n\r]/g, function (ch) { return MANIFEST_ESCAPES[ch]; });
  }

  function manifestElement(name, attrs, close) {
    return '<' + name + attrs.map(function (pair) {
      return ' ' + pair[0] + '="' + manifestAttr(pair[1]) + '"';
    }).join('') + (close === false ? '>' : '/>');
  }

  /** verification.manifest_xml: the manifest as the toolkit writes it, one
   * element to a line, every attribute always present and in one order.
   * @param {Rec} facts manifestFacts
   * @param {string} [code]
   * @param {string[][]} [parts] [name, sha256] pairs, in order
   * @param {string[][]} [carriers] likewise, the parts that carry the code
   * @returns {string} */
  function manifestXml(facts, code, parts, carriers) {
    var d = facts.document, e = facts.engine, c = facts.calibration, r = facts.readiness;
    var lines = [MANIFEST_HEAD, MANIFEST_OPEN,
      manifestElement('document', [['kind', d.kind], ['title', d.title], ['issued', d.issued_on],
        ['code', code || '']]),
      manifestElement('engine', [['name', e.name], ['version', e.version]]),
      manifestElement('calibration', [['name', c.name], ['sha256', c.sha256]]),
      manifestElement('readiness', [['state', r.state]], false)];
    r.items.forEach(function (/** @type {Rec} */ i) {
      lines.push(manifestElement('item', [['state', i.state], ['title', i.title], ['by', i.by],
        ['reason', i.reason]]));
    });
    lines.push('</readiness>', '<evidence>');
    facts.evidence.forEach(function (/** @type {Rec} */ f) {
      lines.push(manifestElement('file', [['what', f.what], ['name', f.name], ['sha256', f.sha256]]));
    });
    lines.push('</evidence>', '<parts>');
    (parts || []).forEach(function (p) {
      lines.push(manifestElement('part', [['name', p[0]], ['sha256', p[1]]]));
    });
    lines.push('</parts>', '<carriers>');
    (carriers || []).forEach(function (p) {
      lines.push(manifestElement('part', [['name', p[0]], ['sha256', p[1]]]));
    });
    lines.push('</carriers>', '</manifest>');
    return lines.join('\n') + '\n';
  }

  /** verification.code_digest: the SHA-256 of the manifest written with no
   * code and no carriers, which the code is a short form of.
   * @param {Rec} facts
   * @param {string[][]} parts
   * @returns {string} */
  function codeDigest(facts, parts) {
    return sha256Hex(manifestXml(facts, '', parts, []));
  }

  function manifestUnescape(value) {
    return value.replace(/&[^;&]*;|&/g, function (token) {
      if (!own(MANIFEST_UNESCAPES, token)) throw new Error('entity');
      return MANIFEST_UNESCAPES[token];
    });
  }

  function manifestParsed(kind, line) {
    var match = MANIFEST_LINES[kind].exec(line);
    if (!match) throw new Error(kind);
    return match.slice(1).map(manifestUnescape);
  }

  function manifestListed(lines, at, kind, end) {
    var out = [];
    while (at < lines.length && lines[at] !== end) {
      out.push(manifestParsed(kind, lines[at]));
      at += 1;
    }
    if (at >= lines.length) throw new Error(end);
    return { items: out, at: at + 1 };
  }

  function partNamesOk(pairs) {
    for (var i = 0; i < pairs.length; i++) {
      var name = pairs[i][0];
      if (!name || name === MANIFEST_PART || !HEX64_RE.test(pairs[i][1])) return false;
      if (i && codePointCompare(pairs[i - 1][0], name) >= 0) return false;
    }
    return true;
  }

  /** verification.read_manifest: {facts, code, parts, carriers} from a
   * manifest's text, or null unless the text is exactly what manifestXml
   * writes for what it holds and what it holds is sound.
   * @param {*} text
   * @returns {Rec|null} */
  function readManifest(text) {
    if (typeof text !== 'string' || text.slice(-1) !== '\n') return null;
    var lines = text.slice(0, -1).split('\n');
    var facts, code, parts, carriers;
    try {
      if (lines[0] !== MANIFEST_HEAD || lines[1] !== MANIFEST_OPEN ||
          lines[lines.length - 1] !== '</manifest>' || lines.length < 6) {
        throw new Error('frame');
      }
      var doc = manifestParsed('document', lines[2]);
      var engine = manifestParsed('engine', lines[3]);
      var cal = manifestParsed('calibration', lines[4]);
      var state = manifestParsed('readiness', lines[5])[0];
      var items = manifestListed(lines, 6, 'item', '</readiness>');
      var at = items.at;
      if (lines[at] !== '<evidence>') throw new Error('evidence');
      var files = manifestListed(lines, at + 1, 'file', '</evidence>');
      at = files.at;
      if (lines[at] !== '<parts>') throw new Error('parts');
      var listed = manifestListed(lines, at + 1, 'part', '</parts>');
      at = listed.at;
      if (lines[at] !== '<carriers>') throw new Error('carriers');
      var carried = manifestListed(lines, at + 1, 'part', '</carriers>');
      if (carried.at !== lines.length - 1) throw new Error('trailing');
      var readiness = { state: state, items: items.items.map(function (i) {
        return { state: i[0], title: i[1], by: i[2], reason: i[3] };
      }) };
      if (READINESS_STATES.indexOf(state) < 0 ||
          readiness.items.some(function (i) { return i.state !== 'unmet' && i.state !== 'overridden'; }) ||
          readiness.items.some(function (i) { return i.state === 'unmet' && (i.by || i.reason); }) ||
          (state === 'not_assessed' && readiness.items.length) ||
          (state !== 'not_assessed' && state !== readinessStateOf(readiness.items))) {
        throw new Error('readiness');
      }
      var calibration = cal[0] || cal[1] ? { name: cal[0], sha256: cal[1] } : null;
      facts = manifestFacts(doc[0], doc[1], doc[2], engine, calibration, readiness,
        files.items.map(function (f) { return { what: f[0], name: f[1], sha256: f[2] }; }));
      code = doc[3];
      parts = listed.items;
      carriers = carried.items;
      var held = Object.create(null);
      parts.forEach(function (p) { held[p[0]] = true; });
      if (!partNamesOk(parts) || !partNamesOk(carriers) ||
          carriers.some(function (p) { return own(held, p[0]); })) {
        throw new Error('parts');
      }
      if (!DOCUMENT_CODE_RE.test(code) || parseDocumentCode(code) !== code) throw new Error('code');
    } catch (e) {
      return null;
    }
    if (manifestXml(facts, code, parts, carriers) !== text) return null;
    return { facts: facts, code: code, parts: parts, carriers: carriers };
  }

  function documentRecordOf(facts, code, digest) {
    var d = facts.document;
    return { code: code, sha256: digest, kind: d.kind, title: d.title, issued_on: d.issued_on,
      readiness: facts.readiness.state };
  }

  function asBytes(data) {
    return typeof data === 'string' ? utf8Encode(data)
      : new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
  }

  /** verification.seal_package: a document's parts with its manifest added.
   * `entries` maps each part's name to its bytes (or text), without the
   * parts that carry the code; the manifest is linked from the document's
   * relationships, .xml given a content type where it has none, every part
   * hashed, the code worked out, and makeCarriers(code) asked for the parts
   * that print it. Returns {entries, manifest, code, sha256, record}.
   * @param {Object<string, Uint8Array|string>} entries
   * @param {Rec} facts manifestFacts
   * @param {function(string): Object<string, Uint8Array|string>} [makeCarriers]
   * @returns {Rec} */
  function sealPackage(entries, facts, makeCarriers) {
    if (own(entries, MANIFEST_PART)) throw new Error('the package already has a part named ' + MANIFEST_PART);
    /** @type {Object<string, Uint8Array>} */
    var out = Object.create(null);
    Object.keys(entries).forEach(function (name) { out[name] = asBytes(entries[name]); });
    var decoder = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true });
    var rels = decoder.decode(out[DOCUMENT_RELS]);
    if (rels.split('</Relationships>').length !== 2) {
      throw new Error("the document's relationships are not one list");
    }
    var link = '<Relationship Id="' + MANIFEST_REL_ID + '" Type="' + MANIFEST_REL_TYPE +
      '" Target="../' + MANIFEST_PART + '"/>';
    out[DOCUMENT_RELS] = utf8Encode(rels.replace('</Relationships>', link + '</Relationships>'));
    var types = decoder.decode(out[CONTENT_TYPES]);
    if (types.indexOf('Extension="xml"') < 0) {
      var start = types.indexOf('<Types');
      var end = types.indexOf('>', start) + 1;
      out[CONTENT_TYPES] = utf8Encode(types.slice(0, end) + XML_DEFAULT + types.slice(end));
    }
    var parts = Object.keys(out).sort(codePointCompare).map(function (name) {
      return [name, sha256Hex(out[name])];
    });
    var code = documentCode(codeDigest(facts, parts));
    var made = makeCarriers ? makeCarriers(code) : Object.create(null);
    var carriers = Object.keys(made).sort(codePointCompare).map(function (name) {
      if (own(out, name) || name === MANIFEST_PART) throw new Error('a part that carries the code is named twice');
      out[name] = asBytes(made[name]);
      return [name, sha256Hex(out[name])];
    });
    var manifest = manifestXml(facts, code, parts, carriers);
    out[MANIFEST_PART] = utf8Encode(manifest);
    var digest = sha256Hex(out[MANIFEST_PART]);
    return { entries: out, manifest: manifest, code: code, sha256: digest,
      record: documentRecordOf(facts, code, digest) };
  }

  /** verification.clean_issue_records: issue records as both engines keep
   * them, each well formed, one per document hash, in the order issued (by
   * date, then code, then hash); a record that is not one is dropped.
   * @param {*} raw
   * @returns {Rec[]} */
  function cleanIssueRecords(raw) {
    /** @type {Rec[]} */
    var kept = [];
    var seen = Object.create(null);
    (Array.isArray(raw) ? raw : []).forEach(function (entry) {
      if (!entry || typeof entry !== 'object' || Array.isArray(entry)) return;
      if (!RECORD_KEYS.every(function (key) { return typeof entry[key] === 'string'; })) return;
      /** @type {Rec} */
      var record = {};
      RECORD_KEYS.forEach(function (key) { record[key] = manifestText(entry[key]); });
      if (parseDocumentCode(record.code) !== record.code || !HEX64_RE.test(record.sha256) ||
          (record.issued_on && isoDay(record.issued_on) === null) ||
          READINESS_STATES.indexOf(record.readiness) < 0 || own(seen, record.sha256)) return;
      seen[record.sha256] = true;
      kept.push(record);
    });
    return kept.sort(function (a, b) {
      return codePointCompare(a.issued_on, b.issued_on) || codePointCompare(a.code, b.code) ||
        codePointCompare(a.sha256, b.sha256);
    });
  }

  /** verification.borehole_records: the issue records among raw of
   * documents about the borehole itself, which its asset record keeps.
   * @param {*} raw
   * @returns {Rec[]} */
  function boreholeRecords(raw) {
    return cleanIssueRecords(raw).filter(function (r) { return BOREHOLE_KINDS.indexOf(r.kind) >= 0; });
  }

  /** verification.issue_records_of: every issue record a saved project file
   * carries, as either app wrote it: the project's own (issued) and its
   * asset record's (documents, at the top of a Python app's file and in the
   * state of this app's).
   * @param {*} payload
   * @returns {Rec[]} */
  function issueRecordsOf(payload) {
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return [];
    var raw = [];
    var state = payload.state && typeof payload.state === 'object' && !Array.isArray(payload.state)
      ? payload.state : {};
    [payload.asset, state.asset].forEach(function (asset) {
      if (asset && typeof asset === 'object' && !Array.isArray(asset) && Array.isArray(asset.documents)) {
        raw = raw.concat(asset.documents);
      }
    });
    [payload.issued, state.issued].forEach(function (issued) {
      if (Array.isArray(issued)) raw = raw.concat(issued);
    });
    return cleanIssueRecords(raw);
  }

  function issuedWords(day) {
    return day ? phrase('verification.on_day', { date: day }) : phrase('verification.on_no_day');
  }

  /** verification.lookup_code: what the issue records say of a code typed in
   * or read off a cover: {code, records, lines}.
   * @param {*} text
   * @param {*} records
   * @returns {Rec} */
  function lookupCode(text, records) {
    var held = cleanIssueRecords(records);
    var code = parseDocumentCode(text);
    if (code === null) {
      return { code: null, records: [], lines: [phrase('verification.code_unreadable',
        { code: manifestText(String(text || '')) })] };
    }
    var found = held.filter(function (r) { return r.code === code; });
    if (!found.length) {
      return { code: code, records: [], lines: [phrase('verification.code_not_found',
        { n: held.length, code: code })] };
    }
    var words = phraseTable('verification.readiness_words');
    return { code: code, records: found, lines: found.map(function (r) {
      return phrase('verification.code_found', { code: code, title: r.title, when: issuedWords(r.issued_on),
        readiness: words[r.readiness], sha256: r.sha256 });
    }) };
  }

  var CRC32_TABLE = (function () {
    var table = new Uint32Array(256);
    for (var n = 0; n < 256; n++) {
      var c = n;
      for (var k = 0; k < 8; k++) c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
      table[n] = c >>> 0;
    }
    return table;
  }());

  function crc32Of(bytes) {
    var c = 0xFFFFFFFF;
    for (var i = 0; i < bytes.length; i++) c = CRC32_TABLE[(c ^ bytes[i]) & 0xFF] ^ (c >>> 8);
    return (c ^ 0xFFFFFFFF) >>> 0;
  }

  /** verification.read_package: the parts of a ZIP package by name, or null
   * when it is not one this toolkit reads, rule for rule as the Python reads
   * it: one end-of-directory record at the end of the file with nothing after
   * its comment, on one disk and not ZIP64, its directory running up to it;
   * no entry encrypted, compressed by anything but DEFLATE, named twice or
   * named in other than ASCII without the UTF-8 flag; each local header
   * naming its entry and method as the directory does, its data before the
   * directory, and its size and CRC-32 as the directory says, with nothing
   * after the end of its DEFLATE stream.
   * @param {Uint8Array|ArrayBuffer} bytes
   * @returns {Object<string, Uint8Array>|null} */
  function readPackage(bytes) {
    var data = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
    var n = data.length;
    var view = new DataView(data.buffer, data.byteOffset, data.byteLength);
    var eocd = -1, at;
    for (at = n - 22; at >= 0 && at >= n - 22 - 65535; at--) {
      if (view.getUint32(at, true) === 0x06054b50) { eocd = at; break; }
    }
    if (eocd < 0) return null;
    var count = view.getUint16(eocd + 10, true), size = view.getUint32(eocd + 12, true);
    var start = view.getUint32(eocd + 16, true);
    if (view.getUint16(eocd + 4, true) || view.getUint16(eocd + 6, true) ||
        view.getUint16(eocd + 8, true) !== count || eocd + 22 + view.getUint16(eocd + 20, true) !== n ||
        start + size !== eocd || count === 0xFFFF || start === 0xFFFFFFFF) return null;
    /* no prototype, so a part named __proto__ is a part like any other */
    /** @type {Object<string, Uint8Array>} */
    var parts = Object.create(null);
    var total = 0, utf8 = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true });
    at = start;
    for (var k = 0; k < count; k++) {
      if (at + 46 > eocd || view.getUint32(at, true) !== 0x02014b50) return null;
      var flags = view.getUint16(at + 8, true), method = view.getUint16(at + 10, true);
      var crc = view.getUint32(at + 16, true), csize = view.getUint32(at + 20, true);
      var usize = view.getUint32(at + 24, true), nameLen = view.getUint16(at + 28, true);
      var extraLen = view.getUint16(at + 30, true), commentLen = view.getUint16(at + 32, true);
      var local = view.getUint32(at + 42, true);
      var rawName = data.subarray(at + 46, at + 46 + nameLen);
      at += 46 + nameLen + extraLen + commentLen;
      if (at > eocd || (flags & 0x2041) || (method !== 0 && method !== 8)) return null;
      var name;
      if (flags & 0x800) {
        try {
          name = utf8.decode(rawName);
        } catch (e) {
          return null;
        }
      } else {
        for (var b = 0; b < rawName.length; b++) if (rawName[b] >= 0x80) return null;
        name = String.fromCharCode.apply(null, Array.from(rawName));
      }
      if (local + 30 > start || view.getUint32(local, true) !== 0x04034b50) return null;
      var lNameLen = view.getUint16(local + 26, true), lExtraLen = view.getUint16(local + 28, true);
      if (view.getUint16(local + 8, true) !== method || lNameLen !== nameLen) return null;
      for (var j = 0; j < nameLen; j++) if (data[local + 30 + j] !== rawName[j]) return null;
      var begin = local + 30 + lNameLen + lExtraLen;
      if (begin + csize > start) return null;
      if (name.slice(-1) === '/') continue;
      if (own(parts, name) || usize > MAX_PART_BYTES) return null;
      total += usize;
      if (total > MAX_PACKAGE_BYTES) return null;
      var stored = data.subarray(begin, begin + csize), body;
      if (method === 0) {
        body = stored;
      } else {
        try {
          body = inflateRaw(stored, usize);
        } catch (e) {
          return null;
        }
      }
      if (body.length !== usize || crc32Of(body) !== crc) return null;
      parts[name] = body;
    }
    if (at !== eocd) return null;
    return parts;
  }

  function manifestOf(parts) {
    if (!own(parts, MANIFEST_PART)) return null;
    var text;
    try {
      text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(parts[MANIFEST_PART]);
    } catch (e) {
      return null;
    }
    return readManifest(text);
  }

  function codeOf(manifest) {
    return documentCode(codeDigest(manifest.facts, manifest.parts));
  }

  /** verification.document_record: the issue record of a document the
   * toolkit has just written, from its own bytes, or null.
   * @param {Uint8Array|ArrayBuffer} bytes
   * @returns {Rec|null} */
  function documentRecord(bytes) {
    var parts = readPackage(bytes);
    if (parts === null) return null;
    var manifest = manifestOf(parts);
    if (!manifest || codeOf(manifest) !== manifest.code) return null;
    return documentRecordOf(manifest.facts, manifest.code, sha256Hex(parts[MANIFEST_PART]));
  }

  function partLabel(name) {
    var names = phraseTable('verification.part_names');
    if (own(names, name)) return phrase('verification.part_label', { name: name, what: names[name] });
    if (name.indexOf('word/media/') === 0) {
      return phrase('verification.part_label', { name: name, what: names['word/media'] });
    }
    return name;
  }

  function readinessLine(readiness) {
    var state = readiness.state;
    if (state === 'ready') return phrase('verification.readiness_ready');
    if (state === 'not_assessed') return phrase('verification.readiness_not_assessed');
    var overridden = readiness.items.filter(function (i) { return i.state === 'overridden'; })
      .map(function (i) {
        return i.by ? phrase('verification.overridden_by', { title: i.title, by: i.by }) : i.title;
      }).join('; ');
    if (state === 'ready_with_overrides') {
      return phrase('verification.readiness_overrides', { titles: overridden });
    }
    var line = phrase('verification.readiness_not_ready', { titles: readiness.items
      .filter(function (i) { return i.state === 'unmet'; })
      .map(function (i) { return i.title; }).join('; ') });
    if (overridden) line += ' ' + phrase('verification.readiness_also_overridden', { titles: overridden });
    return line;
  }

  function evidenceLine(evidence) {
    if (!evidence.length) return phrase('verification.evidence_none');
    var files = evidence.map(function (f) {
      return f.what
        ? phrase('verification.evidence_file', { name: f.name, what: f.what, short: f.sha256.slice(0, 16) })
        : phrase('verification.evidence_file_bare', { name: f.name, short: f.sha256.slice(0, 16) });
    }).join('; ');
    return phrase('verification.evidence_some', { n: evidence.length, files: files });
  }

  function engineLine(facts) {
    return phrase('verification.engine_line', { engine: facts.engine.name, version: facts.engine.version,
      calibration: facts.calibration.name || phrase('verification.calibration_unstated'),
      when: issuedWords(facts.document.issued_on) });
  }

  function verificationAnswered(report, issued, changed, readiness, evidence, engine) {
    report.answers = { issued: issued, changed: changed, readiness: readiness, evidence: evidence };
    var headline = phraseTable('verification.verdicts')[report.verdict];
    report.lines = [headline, issued, changed, readiness, evidence, engine || '']
      .filter(function (line) { return line; });
    return report;
  }

  /** verification.verify_document: whether the toolkit issued a .docx,
   * whether it has changed since, whether it was certifiable or
   * provisional, and which evidence it was issued from. `records` are the
   * issue records to check it against, or null when none were given.
   * @param {Uint8Array|ArrayBuffer} bytes
   * @param {*} [records]
   * @returns {Rec} */
  function verifyDocument(bytes, records) {
    /** @type {Rec} */
    var report = { verdict: 'unreadable', issued: 'unreadable', code: '', sha256: '', facts: null,
      changed: [], missing: [], added: [], record: null, answers: {}, lines: [] };
    var parts = readPackage(bytes);
    if (parts === null) {
      return verificationAnswered(report, phrase('verification.issued_unreadable'), '', '', '');
    }
    if (!own(parts, MANIFEST_PART)) {
      report.verdict = report.issued = 'no_manifest';
      return verificationAnswered(report, phrase('verification.issued_no_manifest'),
        phrase('verification.changed_unknown'), '', '');
    }
    var manifest = manifestOf(parts);
    if (!manifest) {
      report.verdict = report.issued = 'damaged_manifest';
      return verificationAnswered(report, phrase('verification.issued_damaged'),
        phrase('verification.changed_unknown'), '', '');
    }
    var digest = sha256Hex(parts[MANIFEST_PART]);
    report.code = manifest.code;
    report.sha256 = digest;
    if (codeOf(manifest) !== manifest.code) {
      report.verdict = report.issued = 'altered_manifest';
      return verificationAnswered(report, phrase('verification.issued_altered', { code: manifest.code }),
        phrase('verification.changed_unknown'), '', '');
    }
    var facts = manifest.facts, code = manifest.code;
    report.facts = facts;
    /** @type {Object<string, string>} */
    var listed = Object.create(null);
    manifest.parts.concat(manifest.carriers).forEach(function (p) { listed[p[0]] = p[1]; });
    var names = Object.keys(listed).sort(codePointCompare);
    var held = /** @type {Object<string, Uint8Array>} */ (parts);
    report.changed = names.filter(function (name) {
      return own(held, name) && sha256Hex(held[name]) !== listed[name];
    });
    report.missing = names.filter(function (name) { return !own(held, name); });
    report.added = Object.keys(held).filter(function (name) {
      return !own(listed, name) && name !== MANIFEST_PART;
    }).sort(codePointCompare);
    var altered = report.changed.length || report.missing.length || report.added.length;

    var issued;
    if (records === null || records === undefined) {
      report.issued = 'not_checked';
      issued = phrase('verification.issued_not_checked');
    } else {
      var kept = cleanIssueRecords(records);
      var match = kept.filter(function (r) { return r.sha256 === digest; })[0] || null;
      var sameCode = kept.filter(function (r) { return r.code === code; });
      if (match) {
        report.issued = 'matched';
        report.record = match;
        issued = phrase('verification.issued_matched', { code: code });
      } else if (sameCode.length) {
        report.issued = 'record_differs';
        report.record = sameCode[0];
        issued = phrase('verification.issued_record_differs', { code: code });
      } else {
        report.issued = 'no_record';
        issued = phrase('verification.issued_no_record', { n: kept.length, code: code });
      }
    }

    var changed;
    if (altered) {
      var pieces = [];
      if (report.changed.length) {
        pieces.push(phrase('verification.changed_parts', { n: report.changed.length,
          parts: report.changed.map(partLabel).join('; ') }));
      }
      if (report.missing.length) {
        pieces.push(phrase('verification.missing_parts', { parts: report.missing.map(partLabel).join('; ') }));
      }
      if (report.added.length) {
        pieces.push(phrase('verification.added_parts', { parts: report.added.map(partLabel).join('; ') }));
      }
      changed = pieces.join(' ');
    } else {
      changed = phrase('verification.unchanged');
    }
    if (altered || report.issued === 'record_differs') {
      report.verdict = 'changed';
    } else {
      report.verdict = report.issued === 'matched' ? 'verified'
        : report.issued === 'not_checked' ? 'unconfirmed' : 'not_issued';
    }
    return verificationAnswered(report, issued, changed, readinessLine(facts.readiness),
      evidenceLine(facts.evidence), engineLine(facts));
  }

  Object.assign(C, {
    MANIFEST_PART: MANIFEST_PART, DOCUMENT_ENGINE: DOCUMENT_ENGINE, READINESS_STATES: READINESS_STATES,
    BOREHOLE_KINDS: BOREHOLE_KINDS, VERDICTS: VERDICTS,
    documentCode: documentCode, parseDocumentCode: parseDocumentCode, readinessFacts: readinessFacts,
    evidenceEntry: evidenceEntry, calibrationFacts: calibrationFacts, manifestFacts: manifestFacts,
    manifestXml: manifestXml, codeDigest: codeDigest, readManifest: readManifest, sealPackage: sealPackage,
    cleanIssueRecords: cleanIssueRecords, boreholeRecords: boreholeRecords, issueRecordsOf: issueRecordsOf,
    lookupCode: lookupCode, readPackage: readPackage, documentRecord: documentRecord,
    verifyDocument: verifyDocument,
  });

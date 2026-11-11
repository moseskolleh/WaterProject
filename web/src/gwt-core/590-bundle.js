
  /* ================================================== evidence bundles
   * groundwater/bundle.py (PLAN.md step 8.3). One archive for a borehole:
   * raw/ (the source files as uploaded), tables/, figures/ (as the documents
   * embed them), reports/ (the documents issued, each with its own
   * manifest), signatures/, a manifest.json of every file's size and
   * SHA-256 with the engine, the calibration set, each document's code,
   * hash and readiness and the issue records, and a README.txt saying how
   * to check it. A folder that holds nothing carries a note. Every entry is
   * stored, sorted, with one fixed timestamp, so both engines write the same
   * bytes for the same files; the SHA-256 of manifest.json is the bundle's
   * hash. The check confirms a document by an issue record and the other
   * files by the confirmed documents that list them, since a bundle
   * rewritten throughout agrees with itself. */

  var BUNDLE_FORMAT = 'groundwater-toolkit evidence bundle';
  var BUNDLE_VERSION = 1;
  var BUNDLE_MANIFEST = 'manifest.json';
  var BUNDLE_README = 'README.txt';
  var BUNDLE_FOLDERS = ['raw', 'tables', 'figures', 'reports', 'signatures'];
  var BUNDLE_NOTE = 'README.txt';
  /* documents about many boreholes, which the apps leave out of one's
   * bundle unless they are added by hand */
  var PROGRAMME_KINDS = ['calibration', 'rounds'];
  var BUNDLE_VERDICTS = ['verified', 'unconfirmed', 'changed', 'not_issued', 'damaged_manifest',
    'no_manifest', 'unreadable'];
  /* readPackage refuses a count of 0xFFFF; manifest.json is one of them */
  var BUNDLE_MAX_ENTRIES = 0xFFFF - 1;
  /* a document's own check that leaves it sound, whatever the records say */
  var BUNDLE_SOUND = ['verified', 'unconfirmed', 'not_issued'];
  /* what a folder cannot hold, and the control characters XML does carry;
   * built from text, as UNWRITABLE_RE is, since matching them is the point */
  var CONTROL_CLASS = '\\x00-\\x1f\\x7f';
  var BUNDLE_NAME_BAD_RE = new RegExp('[' + CONTROL_CLASS + '<>:"|?*]', 'g');
  var NOT_ASCII_RE = new RegExp('[^' + '\\x00-\\x7f' + ']');
  var BUNDLE_NAME_EDGES_RE = new RegExp('^[' + TRIMMED + '.]+|[' + TRIMMED + '.]+$', 'g');

  /* A to Z folded and nothing else, as bundle._lower folds them */
  function asciiLower(name) {
    return name.replace(/[A-Z]/g, function (ch) { return ch.toLowerCase(); });
  }

  function bundleBytes(data) {
    if (typeof data === 'string') return utf8Encode(data);
    if (data instanceof ArrayBuffer) return new Uint8Array(data);
    if (data && ArrayBuffer.isView(data)) return new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
    return new Uint8Array(0);
  }

  function bytesEqual(a, b) {
    if (a.length !== b.length) return false;
    for (var i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
    return true;
  }

  /** bundle.bundle_name: a file's name as a bundle holds it, the last part
   * of a path with what XML cannot carry dropped, what a folder cannot hold
   * made an underscore and blanks and dots taken off its ends; "file" where
   * nothing is left.
   * @param {*} name
   * @returns {string} */
  function bundleName(name) {
    var text = manifestText(name).split(/[\/\\]/).pop() || '';
    text = text.replace(BUNDLE_NAME_BAD_RE, '_').replace(BUNDLE_NAME_EDGES_RE, '');
    return text || 'file';
  }

  /* one folder's files named as the bundle holds them: sorted by name and
   * hash, a file listed twice once, a different file under a taken name
   * numbered (bundle._placed) */
  function bundlePlaced(items) {
    /** @type {Rec[]} */
    var out = [];
    var taken = Object.create(null), seen = Object.create(null);
    items.slice().sort(function (a, b) {
      return codePointCompare(a.name, b.name) || codePointCompare(a.sha256, b.sha256);
    }).forEach(function (item) {
      var low = asciiLower(item.name);
      if (own(seen, low) && seen[low].indexOf(item.sha256) >= 0) return;
      if (!own(seen, low)) seen[low] = [];
      seen[low].push(item.sha256);
      var name = item.name;
      if (own(taken, asciiLower(name))) {
        var dot = name.lastIndexOf('.');
        var stem = dot > 0 ? name.slice(0, dot) : name, ext = dot > 0 ? name.slice(dot) : '';
        var k = 2;
        while (own(taken, asciiLower(stem + ' (' + k + ')' + ext))) k += 1;
        name = stem + ' (' + k + ')' + ext;
      }
      taken[asciiLower(name)] = true;
      out.push(Object.assign({}, item, { name: name }));
    });
    return out;
  }

  function bundleMadeLine(facts) {
    var when = facts.made_on ? phrase('bundle.on_day', { date: facts.made_on }) : phrase('bundle.on_no_day');
    return phrase('bundle.made', { engine: facts.engine.name, version: facts.engine.version, when: when,
      calibration: facts.calibration.name || phrase('verification.calibration_unstated') });
  }

  /** bundle.bundle_readme: README.txt, from what manifest.json records.
   * @param {Rec} facts
   * @returns {string} */
  function bundleReadme(facts) {
    var folders = phraseTable('bundle.folders');
    var lines = [facts.title ? phrase('bundle.readme_title', { title: facts.title })
      : phrase('bundle.readme_title_bare'), bundleMadeLine(facts), '', phrase('bundle.readme_lead'), ''];
    BUNDLE_FOLDERS.forEach(function (folder) {
      lines.push(phrase('bundle.readme_entry', { name: folder + '/', what: folders[folder] }));
    });
    lines.push(phrase('bundle.readme_entry', { name: BUNDLE_MANIFEST, what: folders.manifest }), '',
      phrase('bundle.readme_check'), phrase('bundle.readme_check_toolkit'),
      phrase('bundle.readme_check_hand'), phrase('bundle.readme_check_outside'));
    return lines.join('\n') + '\n';
  }

  /** bundle.bundle_note: the note a folder that holds nothing carries.
   * @param {string} folder
   * @returns {string} */
  function bundleNote(folder) {
    return phraseTable('bundle.empty_notes')[folder] + '\n';
  }

  /** bundle.bundle_readiness: the readiness of documents taken together,
   * the least ready of those a gate was run for; not_assessed where none
   * was. A choice.
   * @param {string[]} states
   * @returns {string} */
  function bundleReadiness(states) {
    var gated = states.filter(function (s) { return s !== 'not_assessed'; });
    if (!gated.length) return 'not_assessed';
    if (gated.indexOf('not_ready') >= 0) return 'not_ready';
    if (gated.indexOf('ready_with_overrides') >= 0) return 'ready_with_overrides';
    return 'ready';
  }

  /** bundle.bundle_manifest: manifest.json, two-space indents and a
   * newline at the end, as Python's json.dumps writes it.
   * @param {Rec} facts
   * @returns {string} */
  function bundleManifest(facts) {
    return JSON.stringify(facts, null, 2) + '\n';
  }

  /* a sealed document's manifest, hash and parts, or null where it carries
   * none that can be relied on or has changed since it was written;
   * `checked` is what verifyDocument already said of it */
  function bundleDocumentOf(bytes, checked) {
    var report = checked || verifyDocument(bytes, null);
    if (BUNDLE_SOUND.indexOf(report.verdict) < 0) return null;
    var parts = readPackage(bytes);
    var manifest = parts ? manifestOf(parts) : null;
    if (!parts || !manifest) return null;
    return { manifest: manifest, sha256: report.sha256, parts: parts };
  }

  function bundleDocumentEntry(path, held) {
    var facts = held.manifest.facts, readiness = facts.readiness;
    return { path: path, code: held.manifest.code, sha256: held.sha256, kind: facts.document.kind,
      title: facts.document.title, issued_on: facts.document.issued_on, readiness: readiness.state,
      items: readiness.items.map(function (i) {
        return { state: i.state, title: i.title, by: i.by, reason: i.reason };
      }) };
  }

  /** bundle.document_figures: the figures a document embeds, taken out of
   * it as it embeds them (the parts its manifest lists under word/media/,
   * not the cover's code), named after it, for the figures folder; none
   * from a document with no manifest that can be relied on.
   * @param {*} name
   * @param {Uint8Array|ArrayBuffer} bytes
   * @returns {Rec[]} */
  function documentFigures(name, bytes) {
    var held = bundleDocumentOf(bundleBytes(bytes), null);
    if (!held) return [];
    var stem = bundleName(name);
    if (/\.docx$/.test(asciiLower(stem)) && stem.length > '.docx'.length) stem = stem.slice(0, -'.docx'.length);
    /** @type {Rec[]} */
    var out = [];
    var parts = held.parts;
    held.manifest.parts.forEach(function (p) {
      if (p[0].indexOf('word/media/') !== 0) return;
      var image = p[0].slice('word/media/'.length).replace(/\//g, '_');
      out.push({ folder: 'figures', name: stem + ' - ' + image, data: parts[p[0]], what: '' });
    });
    return out;
  }

  /** bundle._stored_zip: a ZIP archive of [name, bytes] pairs as given,
   * each stored, dated 1980-01-01 00:00, a name in ASCII as it is and any
   * other flagged UTF-8, with no extra fields, comments or attributes.
   * @param {Array<[string, Uint8Array]>} entries
   * @returns {Uint8Array} */
  function storedZip(entries) {
    var prepared = entries.map(function (e) {
      return { raw: utf8Encode(e[0]), body: e[1], flags: NOT_ASCII_RE.test(e[0]) ? 0x800 : 0,
        crc: crc32Of(e[1]) };
    });
    var size = 22;
    prepared.forEach(function (p) { size += 30 + 46 + 2 * p.raw.length + p.body.length; });
    var out = new Uint8Array(size);
    var view = new DataView(out.buffer);
    var at = 0;
    var offsets = prepared.map(function (p) {
      var start = at;
      view.setUint32(at, 0x04034b50, true);
      view.setUint16(at + 4, 20, true);
      view.setUint16(at + 6, p.flags, true);
      view.setUint16(at + 12, 0x21, true);
      view.setUint32(at + 14, p.crc, true);
      view.setUint32(at + 18, p.body.length, true);
      view.setUint32(at + 22, p.body.length, true);
      view.setUint16(at + 26, p.raw.length, true);
      out.set(p.raw, at + 30);
      out.set(p.body, at + 30 + p.raw.length);
      at += 30 + p.raw.length + p.body.length;
      return start;
    });
    var directory = at;
    prepared.forEach(function (p, i) {
      view.setUint32(at, 0x02014b50, true);
      view.setUint16(at + 4, 20, true);
      view.setUint16(at + 6, 20, true);
      view.setUint16(at + 8, p.flags, true);
      view.setUint16(at + 14, 0x21, true);
      view.setUint32(at + 16, p.crc, true);
      view.setUint32(at + 20, p.body.length, true);
      view.setUint32(at + 24, p.body.length, true);
      view.setUint16(at + 28, p.raw.length, true);
      view.setUint32(at + 42, offsets[i], true);
      out.set(p.raw, at + 46);
      at += 46 + p.raw.length;
    });
    view.setUint32(at, 0x06054b50, true);
    view.setUint16(at + 8, prepared.length, true);
    view.setUint16(at + 10, prepared.length, true);
    view.setUint32(at + 12, at - directory, true);
    view.setUint32(at + 16, directory, true);
    return out;
  }

  /** bundle.build_evidence_bundle: an evidence bundle of `files`, each
   * {folder, name, data, what}: {bytes, manifest, sha256, facts}. options
   * are borehole, madeOn (an ISO day or blank, never the clock), engine
   * ([name, version], this engine's by default), calibration (as
   * calibrationFacts names it; null is not stated) and records (the
   * project's issue records). A document that does not pass its own check,
   * an unknown folder, a file too large to read back and nothing at all
   * throw.
   * @param {*} title
   * @param {Rec[]} files
   * @param {{borehole?: string, madeOn?: string, engine?: string[], calibration?: Rec|null, records?: Rec[]}} [options]
   * @returns {{bytes: Uint8Array, manifest: string, sha256: string, facts: Rec}} */
  function buildEvidenceBundle(title, files, options) {
    var opts = options || {};
    var when = manifestText(opts.madeOn === undefined ? '' : opts.madeOn);
    if (when && isoDay(when) === null) throw new Error(phrase('verification.bad_date', { date: when }));
    var engine = opts.engine || [DOCUMENT_ENGINE, (GWT.data && GWT.data.version) || ''];
    var cal = { name: '', sha256: '' };
    if (opts.calibration) {
      cal = { name: manifestText(opts.calibration.name), sha256: manifestText(opts.calibration.sha256) };
      if (!cal.name || !HEX64_RE.test(cal.sha256)) throw new Error(phrase('verification.bad_calibration'));
    }
    var words = phraseTable('bundle.what');
    /** @type {Object<string, Rec[]>} */
    var byFolder = {};
    BUNDLE_FOLDERS.forEach(function (folder) { byFolder[folder] = []; });
    /** @type {Object<string, Rec>} */
    var documents = Object.create(null);
    (files || []).forEach(function (item) {
      var folder = manifestText(item.folder);
      if (BUNDLE_FOLDERS.indexOf(folder) < 0) throw new Error(phrase('bundle.bad_folder', { folder: folder }));
      var data = bundleBytes(item.data);
      var name = bundleName(item.name);
      if (data.length > MAX_PART_BYTES) throw new Error(phrase('bundle.file_too_big', { name: name }));
      var digest = sha256Hex(data);
      if (folder === 'reports') {
        var held = bundleDocumentOf(data, null);
        if (!held) {
          throw new Error(phrase('bundle.bad_document', { name: name, why: verifyDocument(data, null).lines[0] }));
        }
        documents[digest] = held;
      }
      byFolder[folder].push({ name: name, sha256: digest, data: data,
        what: manifestText(item.what) || words[folder] });
    });
    if (!BUNDLE_FOLDERS.some(function (folder) { return byFolder[folder].length; })) {
      throw new Error(phrase('bundle.nothing'));
    }
    /** @type {Rec[]} */
    var entries = [];
    /** @type {Rec[]} */
    var docEntries = [];
    BUNDLE_FOLDERS.forEach(function (folder) {
      var placed = bundlePlaced(byFolder[folder]);
      if (!placed.length) {
        entries.push({ path: folder + '/' + BUNDLE_NOTE, what: words.note, data: utf8Encode(bundleNote(folder)) });
      }
      placed.forEach(function (item) {
        var path = folder + '/' + item.name;
        entries.push({ path: path, what: item.what, data: item.data });
        if (folder === 'reports') docEntries.push(bundleDocumentEntry(path, documents[item.sha256]));
      });
    });
    docEntries.sort(function (a, b) { return codePointCompare(a.path, b.path); });
    /** @type {Rec} */
    var facts = {
      format: BUNDLE_FORMAT,
      version: BUNDLE_VERSION,
      title: manifestText(title),
      borehole: manifestText(opts.borehole),
      made_on: when,
      engine: { name: manifestText(engine[0]), version: manifestText(engine[1]) },
      calibration: cal,
      readiness: bundleReadiness(docEntries.map(function (d) { return d.readiness; })),
      documents: docEntries,
      issued: cleanIssueRecords(opts.records || []),
      files: [],
    };
    entries.push({ path: BUNDLE_README, what: words.readme, data: utf8Encode(bundleReadme(facts)) });
    entries.sort(function (a, b) { return codePointCompare(a.path, b.path); });
    if (entries.length + 1 > BUNDLE_MAX_ENTRIES) throw new Error(phrase('bundle.bundle_too_big'));
    facts.files = entries.map(function (e) {
      return { path: e.path, what: e.what, bytes: e.data.length, sha256: sha256Hex(e.data) };
    });
    var manifest = bundleManifest(facts);
    var rawManifest = utf8Encode(manifest);
    var total = rawManifest.length;
    entries.forEach(function (e) { total += e.data.length; });
    if (total > MAX_PACKAGE_BYTES) throw new Error(phrase('bundle.bundle_too_big'));
    /** @type {Array<[string, Uint8Array]>} */
    var pairs = entries.map(function (e) {
      return /** @type {[string, Uint8Array]} */ ([e.path, e.data]);
    });
    pairs.push([BUNDLE_MANIFEST, rawManifest]);
    pairs.sort(function (a, b) { return codePointCompare(a[0], b[0]); });
    return { bytes: storedZip(pairs), manifest: manifest, sha256: sha256Hex(rawManifest), facts: facts };
  }

  function bundleField(obj, key) {
    return own(obj, key) ? obj[key] : undefined;
  }

  function bundleDict(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('object');
    return value;
  }

  function bundleList(value) {
    if (!Array.isArray(value)) throw new Error('list');
    return value;
  }

  function bundleStr(value) {
    if (typeof value !== 'string') throw new Error('text');
    return manifestText(value);
  }

  function bundleInt(value, top) {
    if (typeof value !== 'number' || !Number.isInteger(value) || value < 0 || value > top) {
      throw new Error('count');
    }
    return value;
  }

  function bundleDay(value) {
    var day = bundleStr(value);
    if (day && isoDay(day) === null) throw new Error('day');
    return day;
  }

  function bundleItems(raw, state) {
    var items = bundleList(raw).map(function (value) {
      var item = bundleDict(value);
      return { state: bundleStr(bundleField(item, 'state')), title: bundleStr(bundleField(item, 'title')),
        by: bundleStr(bundleField(item, 'by')), reason: bundleStr(bundleField(item, 'reason')) };
    });
    if (READINESS_STATES.indexOf(state) < 0 ||
        items.some(function (i) { return i.state !== 'unmet' && i.state !== 'overridden'; }) ||
        items.some(function (i) { return i.state === 'unmet' && (i.by || i.reason); }) ||
        (state === 'not_assessed' && items.length) ||
        (state !== 'not_assessed' && state !== readinessStateOf(items))) {
      throw new Error('readiness');
    }
    return items;
  }

  function bundlePathOk(path) {
    if (path === BUNDLE_README) return true;
    var cut = path.indexOf('/');
    if (cut < 0) return false;
    var folder = path.slice(0, cut), name = path.slice(cut + 1);
    return BUNDLE_FOLDERS.indexOf(folder) >= 0 && !!name && bundleName(name) === name;
  }

  /* what a parsed manifest.json records, cleaned as it would have been
   * written; throws where it could not have been written so */
  function bundleFactsFrom(value) {
    var obj = bundleDict(value);
    if (bundleField(obj, 'format') !== BUNDLE_FORMAT ||
        bundleInt(bundleField(obj, 'version'), 1 << 30) !== BUNDLE_VERSION) throw new Error('format');
    var engine = bundleDict(bundleField(obj, 'engine')), cal = bundleDict(bundleField(obj, 'calibration'));
    var calibration = { name: bundleStr(bundleField(cal, 'name')), sha256: bundleStr(bundleField(cal, 'sha256')) };
    if ((calibration.name || calibration.sha256) && !(calibration.name && HEX64_RE.test(calibration.sha256))) {
      throw new Error('calibration');
    }
    var documents = bundleList(bundleField(obj, 'documents')).map(function (raw) {
      var d = bundleDict(raw);
      /** @type {Rec} */
      var entry = { path: bundleStr(bundleField(d, 'path')), code: bundleStr(bundleField(d, 'code')),
        sha256: bundleStr(bundleField(d, 'sha256')), kind: bundleStr(bundleField(d, 'kind')),
        title: bundleStr(bundleField(d, 'title')), issued_on: bundleDay(bundleField(d, 'issued_on')),
        readiness: bundleStr(bundleField(d, 'readiness')) };
      entry.items = bundleItems(bundleField(d, 'items'), entry.readiness);
      if (parseDocumentCode(entry.code) !== entry.code || !HEX64_RE.test(entry.sha256)) throw new Error('document');
      return entry;
    });
    var files = bundleList(bundleField(obj, 'files')).map(function (raw) {
      var f = bundleDict(raw);
      var entry = { path: bundleStr(bundleField(f, 'path')), what: bundleStr(bundleField(f, 'what')),
        bytes: bundleInt(bundleField(f, 'bytes'), MAX_PART_BYTES), sha256: bundleStr(bundleField(f, 'sha256')) };
      if (!bundlePathOk(entry.path) || !HEX64_RE.test(entry.sha256)) throw new Error('file');
      return entry;
    });
    var facts = {
      format: BUNDLE_FORMAT,
      version: BUNDLE_VERSION,
      title: bundleStr(bundleField(obj, 'title')),
      borehole: bundleStr(bundleField(obj, 'borehole')),
      made_on: bundleDay(bundleField(obj, 'made_on')),
      engine: { name: bundleStr(bundleField(engine, 'name')), version: bundleStr(bundleField(engine, 'version')) },
      calibration: calibration,
      readiness: bundleStr(bundleField(obj, 'readiness')),
      documents: documents,
      issued: cleanIssueRecords(bundleList(bundleField(obj, 'issued'))),
      files: files,
    };
    var paths = files.map(function (f) { return f.path; });
    var lowered = Object.create(null);
    for (var i = 0; i < paths.length; i++) {
      if ((i && codePointCompare(paths[i - 1], paths[i]) > 0) || own(lowered, asciiLower(paths[i]))) {
        throw new Error('files');
      }
      lowered[asciiLower(paths[i])] = true;
    }
    if (paths.indexOf(BUNDLE_README) < 0 || BUNDLE_FOLDERS.some(function (folder) {
      return !paths.some(function (p) { return p.indexOf(folder + '/') === 0; });
    })) throw new Error('files');
    var docPaths = documents.map(function (d) { return d.path; });
    for (var j = 1; j < docPaths.length; j++) {
      if (codePointCompare(docPaths[j - 1], docPaths[j]) >= 0) throw new Error('documents');
    }
    var reports = paths.filter(function (p) { return p.indexOf('reports/') === 0; });
    var wanted = docPaths.length ? docPaths : ['reports/' + BUNDLE_NOTE];
    if (reports.length !== wanted.length || reports.some(function (p, k) { return p !== wanted[k]; })) {
      throw new Error('documents');
    }
    if (facts.readiness !== bundleReadiness(documents.map(function (d) { return d.readiness; }))) {
      throw new Error('readiness');
    }
    return facts;
  }

  /** bundle.read_bundle_manifest: what a manifest.json records, or null
   * unless it is exactly what bundleManifest writes for what it holds and
   * what it holds is sound.
   * @param {*} text
   * @returns {Rec|null} */
  function readBundleManifest(text) {
    if (typeof text !== 'string') return null;
    var facts;
    try {
      facts = bundleFactsFrom(JSON.parse(text));
    } catch (e) {
      return null;
    }
    return bundleManifest(facts) === text ? facts : null;
  }

  /* what the toolkit writes at path for these facts, or null */
  function bundleOwnText(path, facts) {
    if (path === BUNDLE_README) return utf8Encode(bundleReadme(facts));
    var cut = path.indexOf('/');
    if (cut >= 0 && path.slice(cut + 1) === BUNDLE_NOTE && BUNDLE_FOLDERS.indexOf(path.slice(0, cut)) >= 0) {
      return utf8Encode(bundleNote(path.slice(0, cut)));
    }
    return null;
  }

  function bundleEvidenceWords(f) {
    var short = f.sha256.slice(0, 16);
    return f.what ? phrase('verification.evidence_file', { name: f.name, what: f.what, short: short })
      : phrase('verification.evidence_file_bare', { name: f.name, short: short });
  }

  function bundleAnswered(report, lines) {
    report.lines = [phraseTable('bundle.verdicts')[report.verdict]].concat(lines);
    return report;
  }

  /** bundle.verify_evidence_bundle: whether every file of a bundle is as it
   * was made, whether each document passes its own check and was issued,
   * and what confirms each file from outside the bundle. `records` are the
   * issue records to check its documents against, or null when none were
   * given.
   * @param {Uint8Array|ArrayBuffer} bytes
   * @param {*} [records]
   * @returns {Rec} */
  function verifyEvidenceBundle(bytes, records) {
    /** @type {Rec} */
    var report = { verdict: 'unreadable', sha256: '', facts: null, files: [], documents: [], lines: [] };
    var parts = readPackage(bundleBytes(bytes));
    if (parts === null) return bundleAnswered(report, [phrase('bundle.unreadable')]);
    if (!own(parts, BUNDLE_MANIFEST)) {
      report.verdict = 'no_manifest';
      return bundleAnswered(report, [phrase('bundle.no_manifest')]);
    }
    var facts = null;
    try {
      facts = readBundleManifest(new TextDecoder('utf-8', { fatal: true, ignoreBOM: true })
        .decode(parts[BUNDLE_MANIFEST]));
    } catch (e) {
      facts = null;
    }
    if (!facts) {
      report.verdict = 'damaged_manifest';
      return bundleAnswered(report, [phrase('bundle.damaged')]);
    }
    var held = /** @type {Object<string, Uint8Array>} */ (parts);
    var known = /** @type {Rec} */ (facts);
    report.sha256 = sha256Hex(held[BUNDLE_MANIFEST]);
    report.facts = known;
    var outside = records === null || records === undefined ? null : cleanIssueRecords(records);
    var ownRecords = Object.create(null);
    known.issued.forEach(function (r) { ownRecords[r.sha256] = true; });

    /** @type {Rec[]} */
    var documents = [];
    var listing = Object.create(null);
    var confirming = Object.create(null);
    /** @type {Rec[]} */
    var evidence = [];
    known.documents.forEach(function (entry) {
      var body = own(held, entry.path) ? held[entry.path] : null;
      /** @type {Rec} */
      var doc = { path: entry.path, present: body !== null, verdict: '', issued: '', code: '', sha256: '',
        agrees: false, held: false, headline: '' };
      if (body !== null) {
        var checked = verifyDocument(body, outside);
        doc.verdict = checked.verdict;
        doc.issued = checked.issued;
        doc.code = checked.code;
        doc.sha256 = checked.sha256;
        doc.headline = checked.lines[0];
        doc.held = own(ownRecords, checked.sha256);
        var sealed = bundleDocumentOf(body, checked);
        if (sealed) {
          doc.agrees = JSON.stringify(bundleDocumentEntry(entry.path, sealed)) === JSON.stringify(entry);
          var manifest = sealed.manifest;
          var hashes = Object.create(null);
          manifest.parts.forEach(function (p) { hashes[p[1]] = true; });
          manifest.facts.evidence.forEach(function (f) { hashes[f.sha256] = true; });
          Object.keys(hashes).forEach(function (digest) {
            if (!own(listing, digest)) listing[digest] = [];
            if (listing[digest].indexOf(entry.path) < 0) listing[digest].push(entry.path);
            if (checked.verdict === 'verified') confirming[digest] = true;
          });
          manifest.facts.evidence.forEach(function (f) {
            if (!evidence.some(function (e) { return evidenceCompare(e, f) === 0; })) evidence.push(f);
          });
        }
      }
      documents.push(doc);
    });
    var byPath = Object.create(null);
    documents.forEach(function (d) { byPath[d.path] = d; });

    /** @type {Rec[]} */
    var files = [];
    var foundHashes = Object.create(null);
    known.files.forEach(function (entry) {
      var path = entry.path;
      var body = own(held, path) ? held[path] : null;
      var found = body === null ? '' : sha256Hex(body);
      if (found) foundHashes[found] = true;
      var state = body === null ? 'missing'
        : (found === entry.sha256 && body.length === entry.bytes ? 'ok' : 'changed');
      var confirmed = 'none';
      if (state === 'ok' && body !== null) {
        var mine = bundleOwnText(path, known);
        if (own(byPath, path)) {
          confirmed = byPath[path].verdict === 'verified' ? 'issue_record' : 'none';
        } else if (mine && bytesEqual(body, mine)) {
          confirmed = 'toolkit';
        } else if (own(confirming, found)) {
          confirmed = 'document';
        }
      }
      files.push({ path: path, what: entry.what, bytes: entry.bytes, sha256: entry.sha256, found: found,
        state: state, confirmed: confirmed,
        listed_by: (own(listing, found) ? listing[found] : []).filter(function (p) { return p !== path; })
          .sort(codePointCompare) });
    });
    var listed = Object.create(null);
    known.files.forEach(function (f) { listed[f.path] = true; });
    Object.keys(held).filter(function (p) { return !own(listed, p) && p !== BUNDLE_MANIFEST; })
      .sort(codePointCompare).forEach(function (path) {
        var found = sha256Hex(held[path]);
        foundHashes[found] = true;
        files.push({ path: path, what: '', bytes: held[path].length, sha256: '', found: found, state: 'added',
          confirmed: 'none', listed_by: [] });
      });
    report.files = files;
    report.documents = documents;

    var broken = files.some(function (f) { return f.state !== 'ok'; }) || documents.some(function (d) {
      return d.present && !(BUNDLE_SOUND.indexOf(d.verdict) >= 0 && d.agrees);
    });
    var verdict;
    if (broken) verdict = 'changed';
    else if (outside === null) verdict = 'unconfirmed';
    else if (documents.some(function (d) { return d.verdict === 'not_issued'; })) verdict = 'not_issued';
    else if (documents.length && files.every(function (f) { return f.confirmed !== 'none'; })) verdict = 'verified';
    else verdict = 'unconfirmed';
    report.verdict = verdict;

    var lines = [];
    if (!files.some(function (f) { return f.state !== 'ok'; })) {
      lines.push(phrase('bundle.files_match', { n: files.length }));
    }
    [['changed', 'bundle.files_changed'], ['missing', 'bundle.files_missing'], ['added', 'bundle.files_added']]
      .forEach(function (pair) {
        var paths = files.filter(function (f) { return f.state === pair[0]; }).map(function (f) { return f.path; });
        if (paths.length) lines.push(phrase(pair[1], { paths: paths.join('; ') }));
      });
    known.documents.forEach(function (entry, i) {
      var doc = documents[i];
      if (!doc.present) return;
      lines.push(phrase('bundle.document_line', { path: doc.path, code: entry.code, verdict: doc.headline }));
      if (BUNDLE_SOUND.indexOf(doc.verdict) >= 0 && !doc.agrees) {
        lines.push(phrase('bundle.document_disagrees', { path: doc.path, code: entry.code }));
      }
    });
    if (outside === null) {
      lines.push(phrase('bundle.confirm_no_records'));
    } else {
      var resting = files.filter(function (f) { return f.confirmed === 'none'; }).map(function (f) { return f.path; });
      lines.push(resting.length
        ? phrase('bundle.confirm_some', { k: files.length - resting.length, n: files.length,
          paths: resting.join('; ') })
        : phrase('bundle.confirm_all', { n: files.length }));
    }
    var missing = evidence.filter(function (f) { return !own(foundHashes, f.sha256); }).sort(evidenceCompare);
    if (missing.length) {
      lines.push(phrase('bundle.not_carried', { n: missing.length,
        files: missing.map(bundleEvidenceWords).join('; ') }));
    }
    lines.push(phrase('bundle.readiness', { words: phraseTable('bundle.readiness_words')[known.readiness] }));
    lines.push(bundleMadeLine(known));
    return bundleAnswered(report, lines);
  }

  Object.assign(C, {
    BUNDLE_FOLDERS: BUNDLE_FOLDERS, BUNDLE_MANIFEST: BUNDLE_MANIFEST, BUNDLE_VERDICTS: BUNDLE_VERDICTS,
    PROGRAMME_KINDS: PROGRAMME_KINDS,
    bundleName: bundleName, bundleReadme: bundleReadme, bundleNote: bundleNote, bundleReadiness: bundleReadiness,
    bundleManifest: bundleManifest, readBundleManifest: readBundleManifest, documentFigures: documentFigures,
    buildEvidenceBundle: buildEvidenceBundle, verifyEvidenceBundle: verifyEvidenceBundle, storedZip: storedZip,
  });

  /* __SECTION_MARK__ */
}(typeof window !== 'undefined' ? window : globalThis));

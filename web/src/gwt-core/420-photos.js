
  /* ================================================================= photos
   * groundwater/photos.py. Where a photograph came from: its capture time,
   * its position and its hash, recorded when it is attached.
   *
   * The hash is of the bytes as attached, before the app downscales a large
   * photograph for storage; `stored` says which copy is kept. The time is
   * the EXIF DateTimeOriginal where the file carries one, otherwise this
   * device's clock at attach, and the record says which. The position is
   * the EXIF GPS where the file carries it, otherwise a device fix taken at
   * attach if one was given, otherwise none, with the reason. Nothing is
   * filled in for a photograph attached before records existed.
   *
   * The EXIF reader is written out here and in Python, tag for tag, so the
   * two engines read the same values from the same file: a library would
   * have been a dependency, and a third reader to keep in step. */

  var PROVENANCE_FORMAT = 1;
  var EXIF_TYPE_SIZE = /** @type {Record<number, number>} */ (
    { 1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8 });
  var EXIF_TIME = /^(\d{4}):(\d{2}):(\d{2}) (\d{2}):(\d{2}):(\d{2})$/;
  var EXIF_OFFSET = /^[+-]\d{2}:\d{2}$/;

  /** The TIFF block of a JPEG's first Exif APP1 segment, or null.
   * @param {Uint8Array} data
   * @returns {Uint8Array|null}
   */
  function exifTiffBlock(data) {
    if (data.length < 2 || data[0] !== 0xFF || data[1] !== 0xD8) return null;
    var pos = 2;
    while (pos + 4 <= data.length) {
      if (data[pos] !== 0xFF) return null;
      var marker = data[pos + 1];
      if (marker === 0xFF) { pos += 1; continue; }
      /* start of scan or end of image: no metadata follows */
      if (marker === 0xDA || marker === 0xD9) return null;
      var length = (data[pos + 2] << 8) | data[pos + 3];
      if (length < 2) return null;
      var body = data.subarray(pos + 4, Math.min(data.length, pos + 2 + length));
      if (marker === 0xE1 && body.length >= 6 && body[0] === 0x45 && body[1] === 0x78 &&
          body[2] === 0x69 && body[3] === 0x66 && body[4] === 0 && body[5] === 0) {
        return body.subarray(6);
      }
      pos += 2 + length;
    }
    return null;
  }

  /** {tag: [type, count, value bytes]} for one IFD; {} where it is broken.
   * @param {Uint8Array} tiff
   * @param {number} offset
   * @param {boolean} little
   * @returns {Record<number, Array<*>>}
   */
  function exifIfd(tiff, offset, little) {
    /** @type {Record<number, Array<*>>} */
    var out = {};
    if (offset < 8 || offset + 2 > tiff.length) return out;
    var view = new DataView(tiff.buffer, tiff.byteOffset, tiff.byteLength);
    var count = view.getUint16(offset, little);
    for (var i = 0; i < count; i++) {
      var at = offset + 2 + 12 * i;
      if (at + 12 > tiff.length) break;
      var tag = view.getUint16(at, little), kind = view.getUint16(at + 2, little);
      var n = view.getUint32(at + 4, little);
      var size = EXIF_TYPE_SIZE[kind];
      if (!size) continue;
      var total = size * n;
      var raw;
      if (total <= 4) {
        raw = tiff.subarray(at + 8, at + 8 + total);
      } else {
        var start = view.getUint32(at + 8, little);
        if (start + total > tiff.length) continue;
        raw = tiff.subarray(start, start + total);
      }
      out[tag] = [kind, n, raw];
    }
    return out;
  }

  /** @param {Array<*>|undefined} entry @returns {string|null} */
  function exifAscii(entry) {
    if (!entry || entry[0] !== 2) return null;
    var text = '';
    for (var i = 0; i < entry[2].length && entry[2][i] !== 0; i++) {
      var c = entry[2][i];
      text += c < 128 ? String.fromCharCode(c) : '�';
    }
    return text.trim();
  }

  /** @param {Array<*>|undefined} entry @param {boolean} little @returns {number|null} */
  function exifLong(entry, little) {
    if (!entry || entry[1] < 1) return null;
    var view = new DataView(entry[2].buffer, entry[2].byteOffset, entry[2].byteLength);
    if (entry[0] === 4) return view.getUint32(0, little);
    if (entry[0] === 3) return view.getUint16(0, little);
    return null;
  }

  /** An unsigned RATIONAL entry as numbers; null if any denominator is 0.
   * @param {Array<*>|undefined} entry @param {boolean} little @returns {number[]|null} */
  function exifRationals(entry, little) {
    if (!entry || entry[0] !== 5) return null;
    var view = new DataView(entry[2].buffer, entry[2].byteOffset, entry[2].byteLength);
    var out = [];
    for (var i = 0; i < entry[1]; i++) {
      var num = view.getUint32(8 * i, little), den = view.getUint32(8 * i + 4, little);
      if (den === 0) return null;
      out.push(num / den);
    }
    return out;
  }

  /** @param {Array<*>|undefined} entry @param {string|null} ref
   * @param {boolean} little @param {number} limit @returns {number|null} */
  function exifDegrees(entry, ref, little, limit) {
    var parts = exifRationals(entry, little);
    if (!parts || parts.length !== 3 || ['N', 'S', 'E', 'W'].indexOf(ref || '') < 0) return null;
    /* added in this order in both engines, so the two give the same double */
    var value = parts[0] + parts[1] / 60.0 + parts[2] / 3600.0;
    if (ref === 'S' || ref === 'W') value = -value;
    return Math.abs(value) <= limit ? value : null;
  }

  /**
   * The capture time and GPS position a JPEG's EXIF carries, as
   * {taken_at, gps: {lat, lon, accuracy_m} | null}; never throws.
   * @param {Uint8Array} data the file's bytes
   * @returns {Rec}
   */
  function readExif(data) {
    /** @type {Rec} */
    var out = { taken_at: null, gps: null };
    try {
      var bytes = new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
      var tiff = exifTiffBlock(bytes);
      if (!tiff || tiff.length < 8) return out;
      var little;
      if (tiff[0] === 0x49 && tiff[1] === 0x49) little = true;
      else if (tiff[0] === 0x4D && tiff[1] === 0x4D) little = false;
      else return out;
      var view = new DataView(tiff.buffer, tiff.byteOffset, tiff.byteLength);
      if (view.getUint16(2, little) !== 42) return out;
      var ifd0 = exifIfd(tiff, view.getUint32(4, little), little);
      var exifAt = exifLong(ifd0[0x8769], little);
      if (exifAt !== null) {
        var exif = exifIfd(tiff, exifAt, little);
        var match = EXIF_TIME.exec(exifAscii(exif[0x9003]) || '');
        /* a camera with no clock set writes zeros, or spaces, which say
         * nothing about when the photograph was taken */
        if (match && Number(match[2]) >= 1 && Number(match[2]) <= 12 &&
            Number(match[3]) >= 1 && Number(match[3]) <= 31) {
          var offset = exifAscii(exif[0x9011]) || '';
          out.taken_at = match[1] + '-' + match[2] + '-' + match[3] + 'T' + match[4] +
            ':' + match[5] + ':' + match[6] + (EXIF_OFFSET.test(offset) ? offset : '');
        }
      }
      var gpsAt = exifLong(ifd0[0x8825], little);
      if (gpsAt !== null) {
        var gps = exifIfd(tiff, gpsAt, little);
        var lat = exifDegrees(gps[2], exifAscii(gps[1]), little, 90);
        var lon = exifDegrees(gps[4], exifAscii(gps[3]), little, 180);
        /* 0, 0 is what a camera without a fix writes, not a place in the sea */
        if (lat !== null && lon !== null && !(lat === 0 && lon === 0)) {
          var error = exifRationals(gps[0x1F], little);
          out.gps = { lat: lat, lon: lon,
            accuracy_m: error && error.length === 1 ? error[0] : null };
        }
      }
    } catch (e) { /* a malformed file has no metadata, and is still a photograph */ }
    return out;
  }

  /**
   * The provenance record for one photograph, from its original bytes. The
   * same record groundwater.photos.photo_provenance makes, field for field.
   * @param {Uint8Array} data the file as attached
   * @param {Rec} options attached_at (UTC, as this device's clock read),
   *   device_fix ({lat, lon, accuracy_m}, used only when the file carries no
   *   position), position_note (why there is none), stored, and sha256 when
   *   the caller has already hashed the same bytes (the page does it with
   *   crypto.subtle, where a 6 MB file costs 120 ms on this thread)
   * @returns {Rec}
   */
  function photoProvenance(data, options) {
    var opts = options || {};
    var bytes = new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
    var exif = readExif(bytes);
    var attachedAt = String(opts.attached_at || '');
    /** @type {Rec} */
    var record = {
      format: PROVENANCE_FORMAT,
      sha256: opts.sha256 ? String(opts.sha256) : sha256Hex(bytes),
      bytes: bytes.length,
      attached_at: attachedAt,
      taken_at: exif.taken_at || attachedAt,
      time_source: exif.taken_at ? 'exif' : 'device',
      position: null,
      position_source: 'none',
      position_note: opts.position_note === undefined ? 'not_requested' : opts.position_note,
      stored: opts.stored || 'original',
    };
    var fix = opts.device_fix;
    if (exif.gps) {
      record.position = exif.gps;
      record.position_source = 'exif';
      record.position_note = '';
    } else if (fix && fix.lat !== null && fix.lat !== undefined &&
               fix.lon !== null && fix.lon !== undefined) {
      record.position = { lat: Number(fix.lat), lon: Number(fix.lon),
        accuracy_m: fix.accuracy_m === null || fix.accuracy_m === undefined
          ? null : Number(fix.accuracy_m) };
      record.position_source = 'device';
      record.position_note = '';
    }
    return record;
  }

  /* photos._reading: a recorded number as a report prints it, a finite
   * number no further from zero than limit, else null; a number written as
   * text is not one */
  function photoReading(value, limit) {
    return typeof value === 'number' && isFinite(value) && Math.abs(value) <= limit ? value : null;
  }

  /* photos._text: text the record keeps, or '' for anything but text */
  function photoText(value) {
    return typeof value === 'string' ? value : '';
  }

  /* photos._accuracy: a position's accuracy as a report prints it */
  function photoAccuracy(value) {
    if (value === null || value === undefined) return phrase('evidence.accuracy_unknown');
    var metres = photoReading(value, Infinity);
    if (metres === null || metres < 0.0) return phrase('evidence.accuracy_unreadable');
    return phrase('evidence.accuracy_m', { m: metres });
  }

  /**
   * A provenance record as a report prints it: {time, position, hash}. A
   * photograph with no record (or one whose hash is not text) gets the
   * catalogue's "no provenance recorded" and nothing else, so nothing is
   * printed that was never recorded. A position is printed only where its
   * latitude and longitude are numbers, finite and within 90 and 180
   * degrees, and its accuracy only where it is a finite number not below
   * zero; a position or an accuracy that cannot be read so, as a
   * hand-edited project file can hold, is said to be unreadable.
   * @param {Rec|null|undefined} record
   * @returns {{time: string, position: string, hash: string}}
   */
  function describePhotoProvenance(record) {
    if (!isRecord(record) || !photoText(/** @type {Rec} */ (record).sha256)) {
      return { time: phrase('evidence.no_provenance'), position: '', hash: '' };
    }
    var rec = /** @type {Rec} */ (record);
    var timeSources = phraseTable('evidence.time_sources');
    var shownTime = photoText(rec.taken_at).replace(/T/g, ' ').replace(/Z$/, '');
    var timeSource = photoText(rec.time_source);
    var time = phrase('evidence.time', { time: shownTime,
      source: own(timeSources, timeSource) ? timeSources[timeSource] : '' });
    var where;
    var position = rec.position;
    var notes = phraseTable('evidence.position_notes');
    var blank = function (/** @type {*} */ v) { return v === null || v === undefined; };
    if (blank(position) || (isRecord(position) && blank(position.lat) && blank(position.lon))) {
      var note = photoText(rec.position_note);
      where = own(notes, note) ? notes[note] : notes.not_requested;
    } else {
      /** @type {Rec} */
      var held = isRecord(position) ? position : {};
      var lat = photoReading(held.lat, 90), lon = photoReading(held.lon, 180);
      if (lat === null || lon === null) {
        where = notes.unreadable;
      } else {
        var sources = phraseTable('evidence.position_sources');
        var source = photoText(rec.position_source);
        where = phrase('evidence.position', { lat: lat, lon: lon, accuracy: photoAccuracy(held.accuracy_m),
          source: own(sources, source) ? sources[source] : '' });
      }
    }
    return { time: time, position: where,
      hash: phrase('evidence.hash', { short: String(rec.sha256).slice(0, 16) }) };
  }

  Object.assign(C, {
    PROVENANCE_FORMAT: PROVENANCE_FORMAT,
    readExif: readExif, photoProvenance: photoProvenance,
    describePhotoProvenance: describePhotoProvenance,
  });

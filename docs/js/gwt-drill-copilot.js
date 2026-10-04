/* gwt-drill-copilot.js - the drilling log co-pilot (PLAN.md step 2.3).
 *
 * A drilling log is written at the rig, from memory and a notebook, and
 * typed up later. What goes wrong goes wrong there: saprolite written down
 * as "clay", which the design then casts off instead of screening; a
 * penetration rate guessed rather than timed; a water strike with no
 * yield; and a day's metres nobody signed for until the invoice came. So
 * this page is the log, kept as the hole is drilled:
 *
 *   - each interval is logged against the one lithology class table both
 *     engines read a description with (C.LITHOLOGY_CLASSES,
 *     groundwater/design/lithology.py). The class is picked from a list,
 *     and a note may add to it only when the row still reads as that class:
 *     "saprolite, clayey" stays saprolite, "weathered rock, sandy" would read
 *     as sand and gravel, and is refused;
 *   - the penetration rate is worked out from the device clock at the two
 *     ends of the interval, in minutes per metre;
 *   - a water strike carries its airlift yield, from a timed container or a
 *     V-notch head, through the engines' own estimate (C.airliftYield);
 *   - each interval can carry a photograph of its cuttings, with the
 *     provenance record every photograph in the app carries
 *     (C.photoProvenance) and the depths of the interval it is of. The
 *     supervision checklist's cutting-samples item does not ask for one at
 *     the readiness gate (drl-cutting-samples-taken, photo "no"): the
 *     samples themselves are bagged, labelled and kept in a box that can
 *     be inspected after the hole is cased, where the seal, the screen and
 *     the disinfection cannot be;
 *   - the supervisor countersigns each day, and a day changed after it was
 *     signed says so;
 *   - the output is the standard drilling log workbook, the layout
 *     src/groundwater/ingestion/templates.py writes and both engines read,
 *     and the driller's daily report in its template's layout, a sheet a
 *     day (PLAN.md rule 6).
 *
 * The log lives in the session under `drillCopilot`, which gwt-store.js
 * keeps in IndexedDB, and is written as each entry is made. Its times are
 * device-clock times, read from one place (GWT.drillCopilotClock when a
 * test sets it), so a log played back at speed is the same code path as a
 * real one. Opening another project or a sample carries it over
 * (FIELD_SESSIONS in gwt-app.js). Nothing here touches the DOM at load
 * time: a Node sandbox can load this file beside support.js and
 * gwt-core.js and write the workbooks (tests/test_drilling_copilot.py).
 *
 * The co-pilot exists in the browser app only; the Streamlit app says so
 * in the same words (text catalogue, drilling_copilot.browser_only).
 */
(function (global) {
  'use strict';

  /** @type {GWTNamespace} */
  var GWT = global.GWT || (global.GWT = {});
  var S = GWT.support, C = GWT.core;
  var el = S.el, field = S.field;

  var KEY = 'drillCopilot';
  var FORMAT = 1;

  /* The order the class list offers, roughly the order a hole meets them
   * in weathered basement. The classes and the words they are read by are
   * the engines' own; only the order of the list is this page's. */
  var CLASS_ORDER = ['topsoil', 'laterite', 'clay', 'sand', 'saprolite', 'weathered',
    'fracture', 'basement', 'other'];

  /* ---------------------------------------------------------------- clock */

  /* The device clock, in milliseconds. A test puts its own clock here to
   * play a log back at speed. */
  function now() {
    return typeof GWT.drillCopilotClock === 'function'
      ? Number(GWT.drillCopilotClock()) : Date.now();
  }

  function pad(n) { return (n < 10 ? '0' : '') + n; }

  /* "14:20", on the device's own clock and time zone */
  function clockText(ms) {
    var d = new Date(ms);
    return pad(d.getHours()) + ':' + pad(d.getMinutes());
  }

  /* The day an entry belongs to, on the device's own calendar. */
  function dayOf(ms) {
    var d = new Date(ms);
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
  }

  /* The day an interval was logged on, as it was named when it was logged.
   * Worked out again from the clock, it follows whatever time zone the
   * device is set to now, and a log reopened under another one moved its
   * evening intervals to the next day: the countersigned day then read as
   * amended, and the next as unsigned, with nothing changed. */
  function dayOfInterval(iv) {
    return typeof iv.day === 'string' && iv.day ? iv.day : dayOf(iv.ended_at);
  }

  /* The device clock with its offset from UTC, so whoever reads the sheet
   * can tell local time from a clock that was simply wrong. */
  function deviceClockText(ms) {
    var d = new Date(ms);
    var offset = -d.getTimezoneOffset();
    var sign = offset < 0 ? '-' : '+';
    var abs = Math.abs(offset);
    return dayOf(ms) + 'T' + pad(d.getHours()) + ':' + pad(d.getMinutes()) +
      ':' + pad(d.getSeconds()) + sign + pad(Math.floor(abs / 60)) + ':' + pad(abs % 60);
  }

  function isNum(v) { return typeof v === 'number' && isFinite(v); }

  function round(value, places) {
    var f = Math.pow(10, places);
    return Math.round(value * f) / f;
  }

  /* ------------------------------------------------------------ lithology */

  /** The classes a row can be logged as, in the order the list offers. */
  function classes() {
    var all = C.LITHOLOGY_CLASSES.concat([C.LITHOLOGY_OTHER]);
    return CLASS_ORDER.map(function (key) {
      var k = all.filter(function (c) { return c.key === key; })[0];
      return { key: k.key, label: k.label };
    });
  }

  function classOf(key) {
    return classes().filter(function (c) { return c.key === key; })[0] || null;
  }

  function cleanNote(note) {
    return String(note === null || note === undefined ? '' : note)
      .replace(/\s+/g, ' ').trim();
  }

  /** The description a row is written with: the class's own label, and the
   * note after it.
   * @param {string} key @param {string} [note] */
  function description(key, note) {
    var k = classOf(key);
    var text = cleanNote(note);
    return k ? k.label + (text ? ', ' + text : '') : '';
  }

  /* Whether a text names a water strike as both readers look for one: the
   * words in lower case, wherever the cell is. Lower-cased first, as they
   * do it, so a letter that only lower-cases to an ASCII one (the Kelvin
   * sign for a k) cannot slip past here and be read there. */
  function namesStrike(text) {
    return /water\s*strike/.test(cleanNote(text).toLowerCase());
  }

  /** Whether a class and a note can be logged together: {description} when
   * the row reads back as the class picked, {problem} when it would not.
   * The readers class a row from its description, first match in the
   * table's order, so a note that names another class's word first can
   * change what the row is; and a note that names a water strike is read
   * as one by both readers, wherever it is written. Given the interval's
   * depths, the row is read as the drawings and the design read it
   * (C.hostClass, lithology.host_class): a depth range after a fracture
   * zone is a zone of its own, and the rest of the row is what is left of
   * the description, so "Fracture zone, 27-28 m" on a 25-30 m row is a
   * metre of fracture in four of Other material.
   * @param {string} key @param {string} [note]
   * @param {number} [top] @param {number} [bottom] */
  function checkLithology(key, note, top, bottom) {
    var k = classOf(key);
    if (!k) return { problem: 'Choose the formation from the list.' };
    var text = cleanNote(note);
    if (namesStrike(text)) {
      return { problem: 'Enter the water strike in its own box, with its depth and ' +
        'airlift yield; written in the description, the readers would take a ' +
        'number in it for a strike depth.' };
    }
    var desc = description(key, text);
    var depths = isNum(top) && isNum(bottom);
    var zones = depths ? C.fractureRanges(desc, top, bottom) : [];
    var read = depths ? C.hostClass(desc, top, bottom) : C.lithologyClass(desc);
    var spilt = zones.filter(function (z) { return z[0] < top || z[1] > bottom; });
    if (zones.length && (read.key !== k.key || spilt.length)) {
      var zone = (spilt.length ? spilt : zones)[0];
      return { problem: 'Written as "' + desc + '", the readers would take ' +
        C.formatG(zone[0]) + '-' + C.formatG(zone[1]) + ' m as a fracture zone of its ' +
        'own' + (spilt.length ? ', outside this interval' : ', and the rest of this ' +
        'interval as ' + read.label) + '. Log the zone as an interval of its own.' };
    }
    if (read.key !== k.key) {
      return { problem: 'Written as "' + desc + '", this row would read as ' +
        read.label + ', not ' + k.label + '. Log it as ' + read.label +
        ' if that is what came up, or word the note without the word that names it.' };
    }
    return { description: desc };
  }

  /* ------------------------------------------------------------ session */

  function app() { return GWT.app; }

  function session() {
    var s = app().store.get(KEY);
    return s && typeof s === 'object' ? s : null;
  }

  /** A log with nothing in it, its header from the project's own site.
   * @param {any} [site] */
  function blankSession(site) {
    var s = site || {};
    return {
      format: FORMAT,
      setup: {
        community: s.community || '', client: s.client || '',
        contractor: s.contractor || '', district: s.district || '',
        boreholeRef: '', method: '', rig: '', driller: '', status: '',
        startDepthM: 0, bitIn: null,
      },
      intervals: [], current: null, signatures: {}, amendments: [],
      gps: null, events: [],
    };
  }

  /* Change the log and write it at once: a time read off the clock cannot
   * be read again. */
  function update(fn) {
    var current = session() || blankSession(app().store.get('site'));
    var next = JSON.parse(JSON.stringify(current));
    var result = fn(next);
    app().store.set(KEY, next);
    if (app().store.flush) app().store.flush();
    return result;
  }

  function logEvent(s, text) {
    s.events.push({ at: now(), text: text });
  }

  /** Minutes per metre, from the device clock at the interval's two ends.
   * @param {any} iv */
  function penetrationMinPerM(iv) {
    var metres = iv.bottom_m - iv.top_m;
    if (!(metres > 0) || !isNum(iv.started_at) || !isNum(iv.ended_at)) return null;
    var minutes = (iv.ended_at - iv.started_at) / 60000;
    return minutes > 0 ? minutes / metres : null;
  }

  function rangeText(iv) {
    return C.formatG(iv.top_m) + '-' + C.formatG(iv.bottom_m);
  }

  function nextTop(s) {
    var last = s.intervals[s.intervals.length - 1];
    return last ? last.bottom_m : (isNum(s.setup.startDepthM) ? s.setup.startDepthM : 0);
  }

  /* -------------------------------------------------------- countersign */

  /** What a countersign covers for one day, as canonical text: each
   * interval's depths, times, class, note, bit and strike with its
   * airlift reading and the yield and basis it gave. A cuttings photograph is not in it: it carries its
   * own capture time and hash, and is often added after the day is
   * signed. */
  function dayRecord(s, day) {
    return s.intervals.filter(function (iv) { return dayOfInterval(iv) === day; })
      .map(function (iv) {
        var st = iv.strike;
        /* the yield and its basis as stored, since they are what the
         * sheets print: worked out again here, a stored figure edited
         * outside the page would be printed and not show */
        return [iv.top_m, iv.bottom_m, iv.started_at, iv.ended_at, iv.lithology,
          iv.note || '', isNum(iv.bit_in) ? iv.bit_in : null,
          st ? [st.depth_m, st.method, st.volume_l === undefined ? null : st.volume_l,
            st.timings_s || null, st.head_mm === undefined ? null : st.head_mm,
            st.reason || '', isNum(st.q_l_per_s) ? st.q_l_per_s : null,
            st.basis || ''] : null];
      });
  }

  /** The SHA-256 of what a countersign covers. It lets the page, and a
   * reader of the sheet, see that a day changed after it was signed. It is
   * not a signature: anyone with the file can change a day and work the
   * digest out again.
   * @param {any} s @param {string} day */
  function dayDigest(s, day) {
    return C.sha256Hex(C.canonicalText(dayRecord(s, day)));
  }

  /** The days the log has intervals on, and the days countersigned, in
   * order. A signed day whose intervals were all taken off the log has
   * none left to list it by, and its countersign went out of the sheets
   * with them; listed, it reads as amended after signing. */
  function days(s) {
    var signed = s.signatures || {};
    var out = Object.keys(signed).filter(function (d) { return (signed[d] || []).length; });
    s.intervals.forEach(function (iv) {
      var d = dayOfInterval(iv);
      if (out.indexOf(d) < 0) out.push(d);
    });
    return out.sort();
  }

  /** 'open' (not signed), 'signed', or 'amended' (changed since the last
   * countersign).
   * @param {any} s @param {string} day */
  function dayStatus(s, day) {
    var signs = (s.signatures || {})[day] || [];
    if (!signs.length) return 'open';
    return signs[signs.length - 1].digest === dayDigest(s, day) ? 'signed' : 'amended';
  }

  function signedDay(s, day) {
    return ((s.signatures || {})[day] || []).length > 0;
  }

  /** The supervisor countersigns a day: their name and the device time,
   * with the digest of what the day holds at that moment.
   * @param {string} day @param {string} name */
  function signDay(day, name) {
    var who = cleanNote(name);
    if (!who) throw new Error('Type the supervisor\'s name to countersign.');
    return update(function (s) {
      var record = dayRecord(s, day);
      if (!record.length) throw new Error('Nothing was logged on ' + day + '.');
      var metres = 0;
      record.forEach(function (row) { metres += row[1] - row[0]; });
      var signature = { name: who, at: now(), digest: dayDigest(s, day),
        intervals: record.length, metres: round(metres, 3) };
      s.signatures[day] = (s.signatures[day] || []).concat([signature]);
      logEvent(s, 'Day ' + day + ' countersigned by ' + who);
      return signature;
    });
  }

  /* A change to a day the supervisor has signed is kept, with when and why:
   * the day is then shown, and written, as amended after signing until it
   * is signed again. Refusing the change would only send the correction to
   * a notebook the log never sees. */
  function amend(s, iv, what, reason) {
    var day = dayOfInterval(iv);
    if (!signedDay(s, day)) return;
    var why = cleanNote(reason);
    if (!why) {
      throw new Error(day + ' is countersigned. Give the reason for the change; ' +
        'the day is then shown as amended after signing until it is signed again.');
    }
    s.amendments.push({ at: now(), day: day, interval: rangeText(iv), what: what,
      reason: why });
  }

  /* ------------------------------------------------------------ entries */

  /** Start drilling an interval now, from the bottom of the last one.
   * @param {{alreadyMin?: number}} [options] the bit started this many
   *   minutes before the page was told */
  function startInterval(options) {
    var opts = options || {};
    return update(function (s) {
      if (s.current) throw new Error('An interval is already being drilled.');
      var t = now();
      if (isNum(opts.alreadyMin) && opts.alreadyMin > 0) t -= opts.alreadyMin * 60000;
      /* A clock set back between intervals would start this one before the
       * last ended: its rate would still come out, from a time that never
       * was, and its day could be one already countersigned. */
      var last = s.intervals[s.intervals.length - 1];
      if (last && !(t >= last.ended_at)) {
        throw new Error('The device clock reads ' + clockText(t) + ', before the last ' +
          'interval ended at ' + clockText(last.ended_at) + '; check the clock before ' +
          'starting.');
      }
      s.current = { top_m: nextTop(s), started_at: t };
      logEvent(s, 'Drilling from ' + C.formatG(s.current.top_m) + ' m');
      return s.current;
    });
  }

  /** The interval being drilled reaches `bottom_m` now. It is logged with
   * its class and note (checkLithology), the bit, and the time it took. With
   * `stop`, drilling stops there (for a rod change of any length, the end
   * of the shift, a breakdown); otherwise the next interval starts at once,
   * from the same moment.
   * @param {{bottom_m: any, lithology: string, note?: string, bit_in?: any,
   *   reason?: string}} form @param {{stop?: boolean}} [options] */
  function endInterval(form, options) {
    var opts = options || {};
    var bottom = Number(form.bottom_m);
    return update(function (s) {
      var cur = s.current;
      if (!cur) throw new Error('Start the interval first: its time starts the rate.');
      if (!(bottom > cur.top_m)) {
        throw new Error('The depth reached has to be below ' + C.formatG(cur.top_m) + ' m.');
      }
      var lith = checkLithology(form.lithology, form.note, cur.top_m, bottom);
      if (lith.problem) throw new Error(lith.problem);
      var t = now();
      if (!(t > cur.started_at)) {
        throw new Error('The device clock reads no later than the start of the ' +
          'interval; check the clock before logging.');
      }
      /* the bit typed for this interval, or the borehole's */
      var typed = form.bit_in;
      var bit = typed !== null && typed !== undefined && typed !== '' && Number(typed) > 0
        ? Number(typed) : s.setup.bitIn;
      var iv = { top_m: cur.top_m, bottom_m: bottom, started_at: cur.started_at,
        ended_at: t, day: dayOf(t), lithology: form.lithology, note: cleanNote(form.note),
        bit_in: isNum(bit) ? bit : null, strike: null, photo: null };
      if (signedDay(s, dayOf(t))) {
        amend(s, iv, 'interval logged after the countersign',
          form.reason || 'drilled after the day was countersigned');
      }
      s.intervals.push(iv);
      s.current = opts.stop ? null : { top_m: bottom, started_at: t };
      logEvent(s, 'Reached ' + C.formatG(bottom) + ' m: ' + lith.description);
      return { index: s.intervals.length - 1, interval: iv,
        minPerM: penetrationMinPerM(iv) };
    });
  }

  /** Stop the interval being drilled without logging it (drilling never
   * got under way). */
  function cancelCurrent() {
    update(function (s) { s.current = null; });
  }

  /** Change a logged interval's class, note or bit. On a signed day the
   * change needs a reason and is kept as an amendment.
   * @param {number} index
   * @param {{lithology?: string, note?: string, bit_in?: any}} changes
   * @param {string} [reason] */
  function correctInterval(index, changes, reason) {
    return update(function (s) {
      var iv = s.intervals[index];
      if (!iv) throw new Error('No interval ' + (index + 1) + '.');
      var key = changes.lithology !== undefined ? changes.lithology : iv.lithology;
      var note = changes.note !== undefined ? changes.note : iv.note;
      var lith = checkLithology(key, note, iv.top_m, iv.bottom_m);
      if (lith.problem) throw new Error(lith.problem);
      var bit = changes.bit_in !== undefined && changes.bit_in !== null &&
        changes.bit_in !== '' ? Number(changes.bit_in) : iv.bit_in;
      var before = description(iv.lithology, iv.note) + (isNum(iv.bit_in)
        ? ', ' + C.formatG(iv.bit_in) + ' in' : '');
      var after = lith.description + (isNum(bit) ? ', ' + C.formatG(bit) + ' in' : '');
      if (before === after) return iv;
      amend(s, iv, 'was "' + before + '", now "' + after + '"', reason);
      iv.lithology = key;
      iv.note = cleanNote(note);
      iv.bit_in = isNum(bit) ? bit : null;
      logEvent(s, 'Interval ' + rangeText(iv) + ' m corrected');
      return iv;
    });
  }

  /** Take the last interval off the log (a depth entered wrongly). On a
   * signed day it needs a reason and is kept as an amendment. Drilling
   * resumes from its top, at its start time.
   * @param {string} [reason] */
  function undoLast(reason) {
    return update(function (s) {
      var iv = s.intervals[s.intervals.length - 1];
      if (!iv) throw new Error('Nothing to undo.');
      amend(s, iv, 'interval taken off the log', reason);
      s.intervals.pop();
      s.current = { top_m: iv.top_m, started_at: iv.started_at };
      logEvent(s, 'Interval ' + rangeText(iv) + ' m taken off the log');
      return iv;
    });
  }

  /** A water strike in a logged interval, with its airlift reading:
   * {depth_m, method: 'bucket'|'vnotch'|'none', volume_l, timings_s,
   * head_mm, reason}. The yield is the engines' own (C.airliftYield). One
   * strike to an interval, as the template has one cell for it; a second
   * strike is a reason to end the interval there.
   * @param {number} index @param {any} reading @param {string} [reason] */
  function setStrike(index, reading, reason) {
    var depth = Number(reading.depth_m);
    var options = {};
    if (reading.method === 'bucket') {
      options = { volume_l: Number(reading.volume_l),
        timings_s: (reading.timings_s || []).map(Number) };
    } else if (reading.method === 'vnotch') {
      options = { head_mm: Number(reading.head_mm) };
    } else {
      options = { reason: reading.reason };
      /* the reason is printed in the airlift basis column of the drilling
       * log, where both readers would take a strike depth from it */
      if (namesStrike(reading.reason)) {
        throw new Error('Give the reason the airlift was not measured without naming ' +
          'the water strike: written on the log, the readers would take a number ' +
          'in it for another strike.');
      }
    }
    var result = C.airliftYield(reading.method, options);
    return update(function (s) {
      var iv = s.intervals[index];
      if (!iv) throw new Error('No interval ' + (index + 1) + '.');
      if (!(depth > iv.top_m && depth <= iv.bottom_m)) {
        throw new Error('The strike has to be within the interval, below ' +
          C.formatG(iv.top_m) + ' m and no deeper than ' + C.formatG(iv.bottom_m) + ' m.');
      }
      var strike = Object.assign({ depth_m: depth, method: reading.method,
        q_l_per_s: result.q_l_per_s, basis: result.basis, flags: result.flags,
        at: now() }, options);
      amend(s, iv, (iv.strike ? 'water strike changed' : 'water strike added') +
        ' at ' + C.formatG(depth) + ' m', reason);
      iv.strike = strike;
      logEvent(s, 'Water strike at ' + C.formatG(depth) + ' m: ' + result.basis);
      return strike;
    });
  }

  /** Remove an interval's water strike. @param {number} index @param {string} [reason] */
  function clearStrike(index, reason) {
    return update(function (s) {
      var iv = s.intervals[index];
      if (!iv || !iv.strike) return null;
      amend(s, iv, 'water strike at ' + C.formatG(iv.strike.depth_m) + ' m removed', reason);
      iv.strike = null;
      return iv;
    });
  }

  /** A cuttings photograph for a logged interval, as the photo slot keeps
   * it (image-slot.js): the picture, its caption and its provenance record,
   * with the depths of the interval it is of beside the record. Null takes
   * it off.
   * @param {number} index @param {any} photo */
  function setPhoto(index, photo) {
    return update(function (s) {
      var iv = s.intervals[index];
      if (!iv) throw new Error('No interval ' + (index + 1) + '.');
      iv.photo = photo ? Object.assign({}, photo,
        { depth: { top_m: iv.top_m, bottom_m: iv.bottom_m } }) : null;
      logEvent(s, (photo ? 'Cuttings photograph for ' : 'Cuttings photograph removed from ') +
        rangeText(iv) + ' m');
      return iv.photo;
    });
  }

  function setSetup(key, value) {
    update(function (s) { s.setup[key] = value; });
  }

  function setGps(fix) {
    update(function (s) { s.gps = fix; });
  }

  function discard() {
    app().store.set(KEY, null);
  }

  /* ------------------------------------------------------------ workbooks */

  function val(v) { return v === null || v === undefined ? '' : v; }

  function easting(s, site) {
    var out = { easting: site.easting, northing: site.northing, zone: '' };
    if (s.gps) {
      var utm = C.geographicToUtm(s.gps.lat, s.gps.lon);
      if ((utm.zone === 28 || utm.zone === 29) && utm.hemisphere === 'N') {
        out = { easting: round(utm.easting, 1), northing: round(utm.northing, 1),
          zone: utm.zone + 'N' };
      }
    }
    if (!out.zone && out.easting) out.zone = C.inferZoneForSierraLeone(out.easting) + 'N';
    return out;
  }

  function signatureText(sig) {
    return sig.name + ', countersigned on this device at ' + deviceClockText(sig.at) +
      ' (day digest ' + sig.digest.slice(0, 16) + ')';
  }

  var NOT_A_SIGNATURE = 'A countersign here is the supervisor\'s name typed on ' +
    'the device and the device time, with a SHA-256 digest of what the day ' +
    'held, which shows a later change; it is not a cryptographic signature.';

  /** The standard drilling log, as src/groundwater/ingestion/templates.py
   * lays it out (header block in rows 2-10, the table from row 11), and two
   * sheets after it that no reader looks at: the cuttings photographs with
   * their provenance, and the countersigns and amendments. The rate column
   * is headed in minutes per metre, which both readers take from the
   * header. After the template's seven columns come the airlift yield and
   * its basis, the device-clock times the rate is worked out from, and the
   * cuttings photograph's hash; their headers name no column a reader takes.
   * @param {any} s @param {any} [site] the project's site fields
   * @param {number} [writtenAt]
   * @returns {Array<{name: string, rows: any[][], widths?: number[]}>} */
  function drillingSheets(s, site, writtenAt) {
    var st = s.setup, place = easting(s, site || {});
    var ivs = s.intervals;
    var deepest = ivs.length ? ivs[ivs.length - 1].bottom_m : '';
    var rows = [
      ['BOREHOLE DRILLING LOG'],
      ['Community', st.community, '', 'Client', st.client],
      ['Contractor', st.contractor, '', 'Borehole Ref. No.', st.boreholeRef],
      ['Drilling start date', ivs.length ? dayOf(ivs[0].started_at) : '', '',
        'Completion date', ''],
      ['Drilling method', st.method, '', 'Total depth (m)', deepest],
      ['District', st.district, '', 'BH status', st.status],
      ['GPS Coordinate East', val(place.easting), '', 'GPS Coordinate North',
        val(place.northing)],
      ['UTM Zone (28N or 29N)', place.zone, '', 'Elevation (m)', val((site || {}).elevation_m)],
      ['Grouting depth (m)', '', '', 'Drill rig', st.rig],
      ['Screens installed (m)', ''],
      ['Depth interval (m)', 'From time', 'To time', 'Penetration rate (min/m)',
        'Sample / lithology description', 'Drilling diameter (in)',
        'Water strike depth (m)', 'Airlift yield (L/s)', 'Airlift basis',
        'Started (device clock)', 'Ended (device clock)', 'Cuttings photo SHA-256'],
    ];
    ivs.forEach(function (iv) {
      var rate = penetrationMinPerM(iv);
      var strike = iv.strike;
      rows.push([rangeText(iv), clockText(iv.started_at), clockText(iv.ended_at),
        rate === null ? '' : round(rate, 2), description(iv.lithology, iv.note),
        val(iv.bit_in), strike ? strike.depth_m : '',
        strike && isNum(strike.q_l_per_s) ? round(strike.q_l_per_s, 3) : '',
        strike ? strike.basis : '', deviceClockText(iv.started_at),
        deviceClockText(iv.ended_at),
        iv.photo && iv.photo.provenance ? iv.photo.provenance.sha256 : '']);
    });
    rows.push([]);
    rows.push(['Notes: written by the drilling log co-pilot. Each description is ' +
      'one of the toolkit\'s lithology classes, with the driller\'s note after it. ' +
      'The penetration rate is the time between the device clock at the top and ' +
      'at the bottom of the interval over its length, rod changes included. The ' +
      'airlift yield is an estimate while drilling, not a pumping test.']);
    rows.push(['Device GPS (WGS84)', s.gps ? C.pyFixed(s.gps.lat, 6) + ', ' +
      C.pyFixed(s.gps.lon, 6) + (isNum(s.gps.accuracy_m) ? ' (within ' +
      C.pyFixed(s.gps.accuracy_m, 0) + ' m)' : '') +
      (isNum(s.gps.at) ? ', ' + deviceClockText(s.gps.at) : '') : 'not taken']);
    rows.push(['Sheet written (device clock)', deviceClockText(isNum(writtenAt) ? writtenAt
      : now())]);

    var photos = [['Depth from (m)', 'Depth to (m)', 'Caption', 'SHA-256', 'Taken at',
      'Time from', 'Position', 'Position from', 'Attached at', 'Copy kept']];
    ivs.forEach(function (iv) {
      var p = iv.photo;
      if (!p) return;
      var rec = p.provenance || {};
      var pos = rec.position;
      photos.push([iv.top_m, iv.bottom_m, val(p.caption), val(rec.sha256),
        val(rec.taken_at), val(rec.time_source),
        pos && isNum(pos.lat) ? C.pyFixed(pos.lat, 6) + ', ' + C.pyFixed(pos.lon, 6) +
          (isNum(pos.accuracy_m) ? ' (within ' + C.pyFixed(pos.accuracy_m, 0) + ' m)' : '')
          : val(rec.position_note),
        val(rec.position_source), val(rec.attached_at), val(rec.stored)]);
    });

    var signs = [['Day', 'Status', 'Countersigned by', 'At (device clock)', 'Intervals',
      'Metres', 'Day digest (SHA-256)']];
    days(s).forEach(function (day) {
      var list = (s.signatures || {})[day] || [];
      var status = dayStatus(s, day);
      if (!list.length) signs.push([day, 'not countersigned', '', '', '', '', '']);
      list.forEach(function (sig, i) {
        signs.push([day, i === list.length - 1 ? (status === 'signed' ? 'countersigned'
          : 'amended after signing') : 'signed before a later amendment',
        sig.name, deviceClockText(sig.at), sig.intervals, sig.metres, sig.digest]);
      });
    });
    signs.push([]);
    signs.push(['Amended at', 'Day', 'Interval (m)', 'Change', 'Reason']);
    (s.amendments || []).forEach(function (a) {
      signs.push([deviceClockText(a.at), a.day, a.interval, a.what, a.reason]);
    });
    signs.push([]);
    signs.push([NOT_A_SIGNATURE]);

    return [
      { name: 'Drilling Log', rows: rows,
        widths: [18, 10, 10, 20, 42, 18, 20, 16, 40, 26, 26, 66] },
      { name: 'Cuttings photos', rows: photos,
        widths: [14, 14, 30, 66, 22, 12, 34, 14, 22, 12] },
      { name: 'Countersigns', rows: signs, widths: [26, 24, 22, 26, 40, 30, 66] },
    ];
  }

  /** The driller's daily report, a sheet a day, each laid out as
   * templates.py write_daily_log_template lays it out with one table row
   * for each interval the day logged: the header block in rows 2-5, the
   * table from row 7, the day's totals two rows under it, and the
   * signature row two rows under those. The supervisor's countersign is
   * written in the supervisor's signature cell; the rig operator's cell is
   * left for a pen.
   * @param {any} s
   * @returns {Array<{name: string, rows: any[][], widths?: number[]}>} */
  function dailySheets(s) {
    var st = s.setup;
    var cumulative = 0;
    return days(s).map(function (day) {
      var ivs = s.intervals.filter(function (iv) { return dayOfInterval(iv) === day; });
      var list = (s.signatures || {})[day] || [];
      var last = list[list.length - 1];
      var status = dayStatus(s, day);
      var metres = 0;
      ivs.forEach(function (iv) { metres += iv.bottom_m - iv.top_m; });
      cumulative += metres;
      var rows = [
        ["DRILLER'S DAILY REPORT"],
        ['Community', st.community, '', 'Borehole Ref. No.', st.boreholeRef],
        ['Date', day, '', 'Drill rig', st.rig],
        ['Contractor', st.contractor, '', 'Supervisor', last ? last.name : ''],
        ['Weather / site conditions', '', '', 'Record taker', st.driller],
        [],
        ['Time from', 'Time to', 'Depth from (m)', 'Depth to (m)',
          'Formation / activity', 'Water strike (m)', 'Airlift yield (L/s)'],
      ];
      ivs.forEach(function (iv) {
        var strike = iv.strike;
        rows.push([clockText(iv.started_at), clockText(iv.ended_at), iv.top_m, iv.bottom_m,
          description(iv.lithology, iv.note), strike ? strike.depth_m : '',
          strike && isNum(strike.q_l_per_s) ? round(strike.q_l_per_s, 3) : '']);
      });
      rows.push([]);
      rows.push(['Metres drilled today', round(metres, 3), 'Cumulative metres',
        round(cumulative, 3), 'Casing installed today (m)', '']);
      rows.push(['Standing / breakdown hours', '', 'Reason', '']);
      rows.push([]);
      rows.push(['Rig operator signature', '', '', 'Supervisor signature',
        last ? signatureText(last) + (status === 'amended'
          ? '; the day was amended after this countersign' : '') : 'not countersigned']);
      rows.push([]);
      rows.push(['Notes: one row per drilled interval or activity (moving, ' +
        'standing, casing). Both signatures are required every day; the ' +
        'office checks invoiced metres against these logs.']);
      rows.push(['Written by the drilling log co-pilot. ' + NOT_A_SIGNATURE]);
      list.forEach(function (sig, i) {
        rows.push(['Countersign ' + (i + 1) + ': ' + signatureText(sig) + ', ' +
          sig.intervals + ' ' + S.plural(sig.intervals, 'interval') + ', ' +
          C.formatG(sig.metres) + ' m.']);
      });
      (s.amendments || []).filter(function (a) { return a.day === day; })
        .forEach(function (a) {
          rows.push(['Amended at ' + deviceClockText(a.at) + ', ' + a.interval + ' m: ' +
            a.what + '. Reason: ' + a.reason + '.']);
        });
      return { name: 'Daily ' + day, rows: rows, widths: [12, 12, 14, 14, 40, 16, 60] };
    });
  }

  function fileStem(s) {
    return S.slug(s.setup.boreholeRef || s.setup.community || 'borehole');
  }

  /* What stops a sheet being written. */
  function writeProblems(s) {
    if (!s || !s.intervals.length) return ['No interval is logged yet.'];
    return [];
  }

  async function drillingWorkbook(s) {
    var problems = writeProblems(s);
    if (problems.length) throw new Error(problems.join(' '));
    return S.writeXlsx(drillingSheets(s, app().store.get('site'), now()));
  }

  async function dailyWorkbook(s) {
    var problems = writeProblems(s);
    if (problems.length) throw new Error(problems.join(' '));
    return S.writeXlsx(dailySheets(s));
  }

  async function downloadDrilling() {
    var s = session();
    var bytes = await drillingWorkbook(s);
    S.download(fileStem(s) + '_drilling_log.xlsx', new Blob([bytes]));
    return bytes;
  }

  async function downloadDaily() {
    var s = session();
    var bytes = await dailyWorkbook(s);
    S.download(fileStem(s) + '_daily_reports.xlsx', new Blob([bytes]));
    return bytes;
  }

  /* The log the co-pilot wrote, as the project's drilling log, read by the
   * same reader as an uploaded one. */
  async function useInProject() {
    var s = session();
    var bytes = new Uint8Array(await drillingWorkbook(s));
    app().store.set('sources.drilling', { name: fileStem(s) + '_drilling_log.xlsx',
      b64: S.bytesToBase64(bytes) });
    await app().recompute();
    app().goto('design');
  }

  /* ================================================================= page */

  var view = null;

  function act(fn) {
    return function () {
      try {
        var out = fn.apply(null, arguments);
        if (out && typeof out.then === 'function') {
          out.then(null, function (e) { S.toast(e.message, 'error'); });
        }
        draw();
        return out;
      } catch (e) {
        S.toast(/** @type {Error} */ (e).message, 'error');
        return null;
      }
    };
  }

  function button(label, onClick, options) {
    var node = S.button(label, onClick, options);
    Object.keys(options || {}).forEach(function (k) {
      if (k.indexOf('data-') === 0) node.setAttribute(k, options[k]);
    });
    return node;
  }

  function page() {
    if (!session()) app().store.set(KEY, blankSession(app().store.get('site')));
    view = { setup: el('div'), drill: el('div', { 'aria-live': 'polite' }),
      log: el('div'), days: el('div'), output: el('div') };
    draw();
    return [
      el('div.page-head', [
        el('div.crumb', 'Investigation'),
        el('h1', 'Drilling log co-pilot'),
        el('p.lead', 'The drilling log kept at the rig, interval by interval: ' +
          'the formation from the toolkit\'s own classes, the rate from the ' +
          'clock, each water strike with its airlift yield, a photograph of ' +
          'the cuttings, and the supervisor\'s countersign each day.'),
      ]),
      el('div.callout.callout-info', el('p', C.phrase('drilling_copilot.browser_only'))),
      view.setup, view.drill, view.log, view.days, view.output,
    ];
  }

  function leave() { view = null; }

  function swap(host, nodes) {
    if (!host) return;
    S.clear(host);
    S.append(host, nodes);
  }

  function draw() {
    if (!view) return;
    var s = session();
    if (!s) return;
    drawSetup(s); drawDrill(s); drawLog(s); drawDays(s); drawOutput(s);
  }

  function drawSetup(s) {
    var st = s.setup;
    function text(key, label, placeholder) {
      return field(label, S.textInput(st[key], function (v) {
        setSetup(key, String(v || '').trim());
      }, { 'data-setup': key, placeholder: placeholder || '' }));
    }
    swap(view.setup, S.card('The borehole', [
      el('div.grid.grid-2', [
        text('community', 'Community'), text('boreholeRef', 'Borehole Ref. No.'),
        text('client', 'Client'), text('contractor', 'Contractor'),
        text('district', 'District'), text('method', 'Drilling method', 'DTH hammer'),
        text('rig', 'Drill rig'), text('driller', 'Driller (record taker)'),
        field('Bit diameter (in)', S.numberInput(st.bitIn, function (v) {
          setSetup('bitIn', isNum(v) && v > 0 ? v : null);
        }, { min: 0, step: 'any', 'data-setup': 'bitIn' })),
        field('Drilling starts at (m)', S.numberInput(st.startDepthM, function (v) {
          setSetup('startDepthM', isNum(v) && v >= 0 ? v : 0);
          draw();
        }, { min: 0, step: 'any', 'data-setup': 'startDepthM',
          disabled: s.intervals.length > 0 })),
      ]),
    ]));
  }

  var form = { bottom_m: null, lithology: '', note: '', bit_in: null };

  function drawDrill(s) {
    var cur = s.current;
    var nodes = [];
    if (!cur) {
      nodes.push(el('p', { 'data-dc': 'idle' }, 'The bit is not turning. Start the ' +
        'interval when it touches ' + C.formatG(nextTop(s)) + ' m: the rate is timed ' +
        'from then.'));
      nodes.push(el('div.btn-row', button('Start drilling', act(function () {
        return startInterval();
      }), { variant: 'primary', 'data-dc': 'start' })));
    } else {
      nodes.push(el('p', { 'data-dc': 'drilling' }, [
        el('strong', 'Drilling from ' + C.formatG(cur.top_m) + ' m since ' +
          clockText(cur.started_at) + '.'),
        ' The rate is timed to the moment the interval is logged.',
      ]));
      var choices = [{ value: '', label: 'Choose the formation' }].concat(
        classes().map(function (k) { return { value: k.key, label: k.label }; }));
      nodes.push(el('div.grid.grid-2', [
        field('Depth reached (m)', S.numberInput(form.bottom_m, function (v) {
          form.bottom_m = v;
        }, { min: 0, step: 'any', 'data-dc': 'bottom' })),
        field('Formation', S.selectInput(form.lithology, choices, function (v) {
          form.lithology = v;
        }, { 'data-dc': 'lithology' }),
        'From the toolkit\'s lithology classes, the ones the design and the ' +
          'Depth Spine read the log by.'),
        field('Note', S.textInput(form.note, function (v) { form.note = v; },
          { 'data-dc': 'note', placeholder: 'colour, grain, hardness' }),
        'Added after the class. A note that would make the row read as ' +
          'another class is refused.'),
        field('Bit diameter (in)', S.numberInput(isNum(form.bit_in) ? form.bit_in
          : s.setup.bitIn, function (v) { form.bit_in = v; },
        { min: 0, step: 'any', 'data-dc': 'bit' })),
      ]));
      nodes.push(el('div.btn-row', [
        button('Log it and drill on', act(function () {
          var out = endInterval(form);
          form = { bottom_m: null, lithology: form.lithology, note: '', bit_in: form.bit_in };
          return out;
        }), { variant: 'primary', 'data-dc': 'log' }),
        button('Log it and stop', act(function () {
          var out = endInterval(form, { stop: true });
          form = { bottom_m: null, lithology: form.lithology, note: '', bit_in: form.bit_in };
          return out;
        }), { variant: 'ghost', 'data-dc': 'log-stop' }),
        button('Not started after all', act(cancelCurrent), { variant: 'ghost' }),
      ]));
    }
    swap(view.drill, S.card('At the rig', nodes));
  }

  function rateText(iv) {
    var rate = penetrationMinPerM(iv);
    return rate === null ? '' : C.pyFixed(rate, 2) + ' min/m';
  }

  function drawLog(s) {
    var askPosition = function () { return !!app().store.get('photoPosition'); };
    var rows = s.intervals.map(function (iv, i) { return { i: i, iv: iv }; }).reverse();
    var items = rows.map(function (row) {
      var iv = row.iv, i = row.i;
      var strike = iv.strike;
      var day = dayOfInterval(iv);
      var signed = signedDay(s, day);
      var slot = GWT.imageSlot ? GWT.imageSlot.create({
        key: 'cuttings-' + i, label: 'Cuttings, ' + rangeText(iv) + ' m',
        hint: 'Laid out beside the metre mark', askPosition: askPosition,
        value: iv.photo,
        onChange: function (v) {
          try { setPhoto(i, v); } catch (e) { S.toast(e.message, 'error'); }
        },
      }) : null;
      return el('div.dc-entry', { 'data-interval': String(i) }, [
        el('p', [el('strong', rangeText(iv) + ' m: ' + description(iv.lithology, iv.note)),
          ' (' + clockText(iv.started_at) + '-' + clockText(iv.ended_at) + ', ' +
          rateText(iv) + (isNum(iv.bit_in) ? ', ' + C.formatG(iv.bit_in) + ' in bit' : '') +
          ')' + (signed ? ' - ' + day + ' is countersigned' : '')]),
        strike ? el('p', { 'data-dc': 'strike' }, 'Water strike at ' +
          C.formatG(strike.depth_m) + ' m: ' + (isNum(strike.q_l_per_s)
          ? C.pyFixed(strike.q_l_per_s, 2) + ' L/s by airlift. ' : '') + strike.basis) : null,
        strike && strike.flags.length ? el('ul', strike.flags.map(function (f) {
          return el('li', { 'data-flag': f.code }, f.message);
        })) : null,
        el('details', [el('summary', strike ? 'Change the water strike' : 'Water strike here'),
          strikeForm(s, i)]),
        slot,
      ]);
    });
    swap(view.log, S.card('The log', items.length ? [
      el('p.muted', 'Newest first. Each interval can take a photograph of its ' +
        'cuttings; it keeps the time, position and SHA-256 every photograph in ' +
        'the app keeps, with the interval\'s depths.'),
      photoPositionNote(),
    ].concat(items).concat([el('div.btn-row', button('Undo the last interval',
      act(function () {
        var last = s.intervals[s.intervals.length - 1];
        var reason = signedDay(s, dayOfInterval(last))
          ? global.prompt('The day is countersigned. Why is the interval coming off?')
          : '';
        if (reason === null) return null;
        return undoLast(reason || '');
      }), { variant: 'ghost' }))]) : S.empty('No interval logged yet.')));
  }

  function photoPositionNote() {
    return S.checkboxInput(app().store.get('photoPosition'),
      'Ask this device for its position when a photograph has none',
      function (v) { app().store.set('photoPosition', !!v); });
  }

  function strikeForm(s, i) {
    var iv = s.intervals[i];
    var f = { depth_m: iv.strike ? iv.strike.depth_m : null, method: 'bucket',
      volume_l: 20, t1: null, t2: null, t3: null, head_mm: null, reason: '' };
    var methods = [{ value: 'bucket', label: 'Timed container' },
      { value: 'vnotch', label: 'V-notch head' }, { value: 'none', label: 'Not measured' }];
    function num(key, label) {
      return field(label, S.numberInput(f[key], function (v) { f[key] = v; },
        { min: 0, step: 'any', 'data-strike': key }));
    }
    return el('div', [
      el('div.grid.grid-2', [
        num('depth_m', 'Strike depth (m)'),
        field('Airlift yield by', S.selectInput(f.method, methods, function (v) {
          f.method = v;
        }, { 'data-strike': 'method' })),
        num('volume_l', 'Container (L)'), num('t1', 'Time 1 (s)'), num('t2', 'Time 2 (s)'),
        num('t3', 'Time 3 (s)'), num('head_mm', 'Head over the notch (mm)'),
        field('Reason, if not measured', S.textInput(f.reason, function (v) {
          f.reason = v;
        }, { 'data-strike': 'reason' })),
      ]),
      el('div.btn-row', [
        button('Record the strike', act(function () {
          var reason = signedDay(s, dayOfInterval(iv))
            ? global.prompt('The day is countersigned. Why is the strike being recorded now?')
            : '';
          if (reason === null) return null;
          return setStrike(i, { depth_m: f.depth_m, method: f.method, volume_l: f.volume_l,
            timings_s: [f.t1, f.t2, f.t3].filter(isNum), head_mm: f.head_mm,
            reason: f.reason }, reason || '');
        }), { variant: 'primary', 'data-strike': 'save' }),
        iv.strike ? button('Remove it', act(function () {
          var reason = signedDay(s, dayOfInterval(iv))
            ? global.prompt('The day is countersigned. Why is the strike coming off?') : '';
          if (reason === null) return null;
          return clearStrike(i, reason || '');
        }), { variant: 'ghost' }) : null,
      ]),
    ]);
  }

  function drawDays(s) {
    var list = days(s);
    swap(view.days, S.card('Countersign each day', list.length ? [
      el('p.muted', NOT_A_SIGNATURE + ' A day changed after it is signed is shown, ' +
        'and written, as amended after signing until it is signed again.'),
    ].concat(list.map(function (day) {
      var status = dayStatus(s, day);
      var ivs = s.intervals.filter(function (iv) { return dayOfInterval(iv) === day; });
      var metres = 0;
      ivs.forEach(function (iv) { metres += iv.bottom_m - iv.top_m; });
      var signs = (s.signatures || {})[day] || [];
      var last = signs[signs.length - 1];
      var name = { value: last ? last.name : '' };
      return el('div.dc-entry', { 'data-day': day, 'data-status': status }, [
        el('p', [el('strong', day + ': '), C.formatG(round(metres, 3)) + ' m in ' +
          ivs.length + ' ' + S.plural(ivs.length, 'interval') + '. ',
        S.badge(status === 'open' ? 'not countersigned' : status === 'signed'
          ? 'countersigned' : 'amended after signing',
        status === 'signed' ? 'ok' : status === 'amended' ? 'warn' : 'info')]),
        last ? el('p.muted', signatureText(last) + '.') : null,
        el('div.grid.grid-2', [
          field('Supervisor', S.textInput(name.value, function (v) { name.value = v; },
            { 'data-sign': day })),
        ]),
        el('div.btn-row', button(status === 'open' ? 'Countersign ' + day
          : 'Countersign ' + day + ' again', act(function () {
          return signDay(day, name.value);
        }), { variant: status === 'signed' ? 'ghost' : 'primary', 'data-sign-button': day })),
      ]);
    })) : S.empty('Each day is countersigned once something is logged on it.')));
  }

  function drawOutput(s) {
    var gps = s.gps;
    var ready = s.intervals.length > 0;
    swap(view.output, S.card('The sheets', [
      el('p.muted', 'The standard drilling log workbook, which the Borehole design ' +
        'page and both apps\' readers take like any other, and the driller\'s daily ' +
        'report in its template\'s layout, a sheet a day.'),
      el('p', { 'data-dc': 'gps' }, gps
        ? 'Position: ' + C.pyFixed(gps.lat, 6) + ', ' + C.pyFixed(gps.lon, 6) +
          (isNum(gps.accuracy_m) ? ', within ' + C.pyFixed(gps.accuracy_m, 0) + ' m' : '') + '.'
        : 'No position taken yet. Stand at the borehole to take it.'),
      el('div.btn-row', [
        button('Take the GPS position', function () { takePosition(); }, { variant: 'ghost' }),
        button('Download the drilling log', act(downloadDrilling),
          { variant: 'primary', disabled: !ready, 'data-dc': 'download-log' }),
        button('Download the daily reports', act(downloadDaily),
          { disabled: !ready, 'data-dc': 'download-daily' }),
        button('Use it as this project\'s drilling log', act(useInProject),
          { variant: 'ghost', disabled: !ready }),
        button('Start a new borehole', function () {
          if (s.intervals.length && !global.confirm('Clear this log of ' +
            s.intervals.length + ' ' + S.plural(s.intervals.length, 'interval') +
            '? Download the sheets first if they are still wanted.')) return;
          app().store.set(KEY, blankSession(app().store.get('site')));
          draw();
        }, { variant: 'ghost' }),
      ]),
    ]));
  }

  /* The device's own fix, asked for only when the button is pressed. */
  function takePosition() {
    var geo = global.navigator && global.navigator.geolocation;
    if (!geo) {
      S.toast('This browser gives no position.', 'warn');
      return Promise.resolve(null);
    }
    return new Promise(function (resolve) {
      geo.getCurrentPosition(function (pos) {
        var fix = { lat: pos.coords.latitude, lon: pos.coords.longitude,
          accuracy_m: isFinite(pos.coords.accuracy) ? pos.coords.accuracy : null,
          at: now() };
        setGps(fix);
        draw();
        resolve(fix);
      }, function (e) {
        S.toast('No position: ' + (e && e.message ? e.message : 'refused') + '.', 'warn');
        resolve(null);
      }, { enableHighAccuracy: true, timeout: 30000, maximumAge: 60000 });
    });
  }

  GWT.drillCopilot = {
    KEY: KEY, classes: classes, description: description, checkLithology: checkLithology,
    blankSession: blankSession, session: session, setSetup: setSetup, setGps: setGps,
    startInterval: startInterval, endInterval: endInterval, cancelCurrent: cancelCurrent,
    correctInterval: correctInterval, undoLast: undoLast, setStrike: setStrike,
    clearStrike: clearStrike, setPhoto: setPhoto, discard: discard,
    penetrationMinPerM: penetrationMinPerM, dayOf: dayOf, days: days,
    dayDigest: dayDigest, dayStatus: dayStatus, signDay: signDay,
    drillingSheets: drillingSheets, dailySheets: dailySheets,
    drillingWorkbook: drillingWorkbook, dailyWorkbook: dailyWorkbook,
    downloadDrilling: downloadDrilling, downloadDaily: downloadDaily,
    useInProject: useInProject, page: page, leave: leave, draw: draw,
    takePosition: takePosition,
  };
  (GWT.loadedBundles || (GWT.loadedBundles = {})).drillCopilot = true;
}(typeof window !== 'undefined' ? window : globalThis));

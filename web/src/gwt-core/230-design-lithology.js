
  /* ======================================================= lithology classes
   * groundwater/design/lithology.py. One reading of the driller's words,
   * shared by every drawing: the borehole drawing, the browser drawing and
   * the Depth Spine each kept their own table of lithology keywords, so the
   * same log was "clay" on one figure, "clay and saprolite" on another and
   * "fresh basement" on a third for an interval the driller had called
   * slightly weathered granite. A description is matched against the classes
   * in order and the first match wins, except that a fracture zone named
   * with a depth range inside a longer interval ("Light colour granite,
   * fracture zone 49-52 m") is a band of its own: the range is the fracture
   * zone, the rest of the interval is the rock it is in, and the drawing
   * used to hatch the whole five metres.
   */
  var LITHOLOGY_RANGE_SOURCE =
    '(\\d+(?:\\.\\d+)?)\\s*(?:-|–|to)\\s*(\\d+(?:\\.\\d+)?)\\s*m\\b';

  /* "fracture zone", "fractured", "fractures": the words that name a
   * fracture. The depths they name are read from the rest of the clause. */
  var FRACTURE_PHRASE_RE = /\bfracture[ds]?\b(?:\s+zones?\b)?/i;

  /* Any depth range written into a description. */
  var ANY_RANGE_RE = new RegExp(LITHOLOGY_RANGE_SOURCE, 'i');

  /* One depth range in a fracture clause: "49-52 m", "49 m to 52 m",
   * "between 49 and 52 m", "49-52 metres", or "49-52" with the unit left
   * off. A range followed by another unit ("2-3 mm", "1-2 per metre") is an
   * aperture or a count, not depths, and is not read. */
  var FRACTURE_NUMBER = '(\\d+(?:\\.\\d+)?)';
  var FRACTURE_METRES = '(?:metres?|meters?|mtrs?|m)\\b';
  var DEPTH_RANGE_SOURCE =
    '(?:between\\s+' + FRACTURE_NUMBER + '\\s*(?:' + FRACTURE_METRES +
    ')?\\s*(?:and|-|to)\\s*' + FRACTURE_NUMBER +
    '|' + FRACTURE_NUMBER + '\\s*(?:' + FRACTURE_METRES + ')?\\s*(?:-|to)\\s*' +
    FRACTURE_NUMBER + ')' +
    '(?:\\s*' + FRACTURE_METRES + ')?' +
    '(?!\\s*(?:mm|cm|%|in\\b|inch|"|ft\\b|feet|per\\b|/|x\\b|\\d|m\\s*/))';

  /* Where a fracture clause ends: a semicolon, a bracket, a line break, a
   * full stop that is not a decimal point, or a comma that does not lead
   * straight on to another range ("fractured zones 49-52 m, 55-56 m" is one
   * clause, "fractured, quartz vein at 52-53 m" is two). */
  var CLAUSE_END_RE = /[;()\n]|\.(?!\d)|,(?!\s*(?:and\s+|&\s*)?\d)/g;

  /* "at" or "from" before the first range belongs to the fracture phrase, so
   * it goes with it when the zone is taken out of the description. */
  var RANGE_LEAD_RE = /\s*\b(?:at|from)\s*$/i;

  /* How far outside the row it is written on a named zone may lie and still
   * be read as a depth. The driller logs "fracture zone 60-62 m" against the
   * 55-60 m row he was drilling when he saw it; a "range" tens of metres from
   * its row is something else (a count, a date), and the row is screened
   * instead. */
  var NAMED_ZONE_REACH_M = 5.0;

  /* In matching order. The patterns are applied to the lowercased
   * description. */
  var LITHOLOGY_CLASSES = [
    ['fracture', 'Fracture zone', '#9FB6CD', 'xx', 'fracture|fissure'],
    ['topsoil', 'Topsoil', '#8B5A2B', '', 'topsoil|top soil'],
    ['laterite', 'Laterite', '#C4703E', '', 'laterit|duricrust'],
    ['saprolite', 'Saprolite', '#D2B48C', '..', 'saprolit|regolith'],
    ['clay', 'Clay', '#B8860B', '--', '\\bclay'],
    ['sand', 'Sand and gravel', '#E8D8A0', '..', '\\bsand|gravel'],
    ['weathered', 'Weathered rock', '#A98F63', '//', 'weather'],
    ['basement', 'Basement rock', '#A9A9A9', '++',
      'granite|gneiss|schist|basement|bedrock|\\brock\\b|fresh'],
  ].map(function (row) {
    return { key: row[0], label: row[1], colour: row[2], hatch: row[3],
      pattern: new RegExp(row[4], 'i') };
  });

  var LITHOLOGY_OTHER = { key: 'other', label: 'Other material',
    colour: '#CCCCCC', hatch: '' };

  /* Words that make an interval clayey ground: a seepage in it is cased and
   * grouted off, not screened, whatever the strike column says. */
  var CLAYEY_RE = /\bclay|laterit|topsoil|top soil/i;

  /** The class of a description as a whole.
   * @param {*} description
   * @returns {{key: string, label: string, colour: string, hatch: string, pattern?: RegExp}}
   */
  function lithologyClass(description) {
    var text = String(description || '').toLowerCase();
    for (var i = 0; i < LITHOLOGY_CLASSES.length; i++) {
      if (LITHOLOGY_CLASSES[i].pattern.test(text)) return LITHOLOGY_CLASSES[i];
    }
    return LITHOLOGY_OTHER;
  }

  /**
   * @param {*} description
   * @returns {boolean}
   */
  function isClayey(description) {
    return CLAYEY_RE.test(String(description || '').toLowerCase());
  }

  /** Read every depth range a fracture phrase names, to the end of its clause
   * (lithology.read_fractures). Only the first range right after the phrase
   * used to be read, so "fractures at 30-31 m and 33-34 m" left 33-34 m
   * behind plain casing, and "between 49 and 52 m", "49 m to 52 m", "49-52
   * metres", "49-52" and an em dash all read as nothing, which screened the
   * whole logged row. Given the row (top, bottom), a range further than
   * NAMED_ZONE_REACH_M from it is not taken as a depth.
   *
   * Returns { ranges, unread, cuts, text }: the zones read; whether a
   * fracture phrase names depths that could not be read as a zone near the
   * row, so the caller treats the whole logged interval as the target as
   * well; and the spans of the dash-normalised text that name the zones
   * read, for taking them out.
   * @param {*} description
   * @param {number|null} [top]
   * @param {number|null} [bottom]
   */
  function readFractures(description, top, bottom) {
    var text = normaliseDashes(String(description || ''));
    var ranges = [], cuts = [], unread = false;
    var phraseRe = new RegExp(FRACTURE_PHRASE_RE.source, 'gi');
    var phrases = [], m;
    while ((m = phraseRe.exec(text)) !== null) {
      phrases.push({ start: m.index, end: m.index + m[0].length });
    }
    var hasRow = top !== null && top !== undefined && bottom !== null && bottom !== undefined;
    phrases.forEach(function (phrase, i) {
      var limit = i + 1 < phrases.length ? phrases[i + 1].start : text.length;
      CLAUSE_END_RE.lastIndex = phrase.end;
      var end = CLAUSE_END_RE.exec(text);
      var clauseEnd = end && end.index < limit ? end.index : limit;
      var clause = text.slice(phrase.end, clauseEnd);
      var read = [], match;
      var rangeRe = new RegExp(DEPTH_RANGE_SOURCE, 'gi');
      while ((match = rangeRe.exec(clause)) !== null) {
        var numbers = match.slice(1).filter(function (g) {
          return g !== undefined;
        }).map(Number);
        var low = Math.min.apply(null, numbers), high = Math.max.apply(null, numbers);
        var near = !hasRow || (low >= /** @type {number} */ (top) - NAMED_ZONE_REACH_M &&
          high <= /** @type {number} */ (bottom) + NAMED_ZONE_REACH_M);
        if (high > low && near) {
          ranges.push([low, high]);
          read.push([match.index, match.index + match[0].length]);
        }
      }
      /* whatever digits are left in the clause name something that was not
       * read as a zone */
      var left = '', cursor = 0;
      read.forEach(function (span) { left += clause.slice(cursor, span[0]); cursor = span[1]; });
      left += clause.slice(cursor);
      if (/\d/.test(left)) {
        unread = true;
      } else if (read.length) {
        var start = read[0][0];
        var lead = RANGE_LEAD_RE.exec(clause.slice(0, start));
        if (lead) start = lead.index;
        cuts.push([phrase.start, phrase.end]);
        cuts.push([phrase.end + start, phrase.end + read[read.length - 1][1]]);
      }
    });
    return { ranges: ranges, unread: unread, cuts: cuts, text: text };
  }

  /** Depth ranges a description names as fractured, in metres.
   * @param {*} description
   * @param {number|null} [top]
   * @param {number|null} [bottom]
   * @returns {number[][]}
   */
  function fractureRanges(description, top, bottom) {
    return readFractures(description, top, bottom).ranges;
  }

  /** The description with its named fracture ranges taken out: "Light colour
   * granite, fracture zone 49-52 m" -> "Light colour granite", so the rock
   * around a named zone is classed as what it is. A fracture phrase whose
   * depths could not all be read is left in, so the row it is written on is
   * still classed as fractured.
   * @param {*} description
   * @param {number|null} [top]
   * @param {number|null} [bottom]
   * @returns {string}
   */
  function hostDescription(description, top, bottom) {
    var reading = readFractures(description, top, bottom);
    var kept = '', cursor = 0;
    reading.cuts.forEach(function (cut) {
      kept += reading.text.slice(cursor, cut[0]);
      cursor = cut[1];
    });
    kept += reading.text.slice(cursor);
    return kept.replace(/\s+/g, ' ').replace(/^[ ,;.]+/, '').replace(/[ ,;.]+$/, '');
  }

  /** The class of the rock a row is logged as, once any zone it names is out
   * (lithology.host_class). "Light colour granite, fracture zone 49-52 m" is
   * basement rock with a fracture zone drawn in it as a band of its own; the
   * class of the whole description would call the row a fracture zone.
   * @param {*} description
   * @param {number|null} [top]
   * @param {number|null} [bottom]
   */
  function hostClass(description, top, bottom) {
    return lithologyClass(fractureRanges(description, top, bottom).length
      ? hostDescription(description, top, bottom) : description);
  }

  /** The log split into bands, each with its class. A fracture zone named
   * with its depths is a band of its own wherever those depths fall, which
   * is not always the row it was written on: the driller logs "fracture zone
   * 60-62 m" against the 55-60 m interval he was drilling when he saw it.
   * The rest of every interval is the rock the description names once the
   * zone is taken out of it. Pass one interval to band it alone (the named
   * zones of the others are then unknown).
   * @param {Rec[]|Rec|null} intervals a log's intervals, or one interval
   */
  function lithologyBands(intervals) {
    var list = Array.isArray(intervals) ? intervals : (intervals ? [intervals] : []);
    var named = [];
    list.forEach(function (iv) {
      fractureRanges(iv.description, Number(iv.top_m), Number(iv.bottom_m))
        .forEach(function (zone) { named.push(zone); });
    });
    named.sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; });
    var fracture = lithologyClass('fracture');
    var bands = [];
    function band(top, bottom, klass) {
      bands.push({ top_m: top, bottom_m: bottom, key: klass.key, label: klass.label,
        colour: klass.colour, hatch: klass.hatch });
    }
    list.slice().sort(function (a, b) { return a.top_m - b.top_m; }).forEach(function (iv) {
      var top = Number(iv.top_m), bottom = Number(iv.bottom_m);
      /* the host rock: the description without the zone it names, so
       * "Light colour granite, fracture zone 49-52 m" is granite here */
      var host = hostClass(iv.description, top, bottom);
      var cursor = top;
      named.forEach(function (zone) {
        var t = Math.max(zone[0], top), b = Math.min(zone[1], bottom);
        if (b <= Math.max(t, cursor)) return;
        if (t > cursor) band(cursor, t, host);
        band(Math.max(t, cursor), b, fracture);
        cursor = b;
      });
      if (cursor < bottom) band(cursor, bottom, host);
    });
    return bands;
  }

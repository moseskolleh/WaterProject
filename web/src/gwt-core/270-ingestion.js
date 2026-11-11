
  /* ============================================================== ingestion
   * groundwater/ingestion/*. Field sheets use a header block of "Label: value"
   * pairs followed by one or more data tables. Labels vary between sheets
   * ("Field Supervisor", "Test conducted by", "Operator"), values sometimes
   * live in the same cell after a colon and sometimes several columns to the
   * right, and numbers may be stored as text with leading zeros.
   *
   * The grid these read is whatever support.readXlsx produced: a ragged array
   * of rows of numbers, strings, Dates and nulls - the same shape openpyxl
   * hands the Python readers.
   */

  /**
   * @param {*} value a cell
   * @returns {string}
   */
  function cleanText(value) {
    if (value === null || value === undefined) return '';
    if (value instanceof Date) return formatIsoDate(value);
    return String(value).replace(/\s+/g, ' ').trim();
  }

  /* Python's str() of the datetime openpyxl hands back for a date cell,
   * which is what clean_text makes of one: "2015-12-08 13:45:00". The time
   * of day used to be written as 00:00:00 whatever the cell held. */
  function formatIsoDate(d) {
    return cellDay(d) + ' ' + cellClock(d) + ':' + twoDigits(d.getUTCSeconds());
  }

  function twoDigits(n) { return String(n).padStart(2, '0'); }

  function cellDay(d) {
    return d.getUTCFullYear() + '-' + twoDigits(d.getUTCMonth() + 1) + '-' +
      twoDigits(d.getUTCDate());
  }

  function cellClock(d) {
    return twoDigits(d.getUTCHours()) + ':' + twoDigits(d.getUTCMinutes());
  }

  /* ingestion/common.py _date_text: a date cell in a header block as
   * "2015-12-08", and as "2015-12-08 13:45" when it carries a time. The
   * Python reader stopped printing the midnight on the report cover; this
   * reader went on writing "2015-12-08 00:00:00" for the same cell. */
  function headerDateText(value) {
    if (!(value instanceof Date)) return value;
    if (value.getUTCHours() || value.getUTCMinutes() || value.getUTCSeconds()) {
      return cellDay(value) + ' ' + cellClock(value);
    }
    return cellDay(value);
  }

  var NUMBER_RE = /[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?/;

  /** Handles plain numbers, leading zeros ("078.7", GPS "0708958"), appended
   * units ("80m", "19.28M", "2,933lts/hr"), thousands separators and stray
   * whitespace. Returns null when no number can be found.
   * @param {*} value a cell
   * @param {number|null} [fallback]
   * @returns {number|null}
   */
  function parseNumber(value, fallback) {
    var dflt = fallback === undefined ? null : fallback;
    if (value === null || value === undefined) return dflt;
    if (typeof value === 'number') return isFinite(value) ? value : dflt;
    if (value instanceof Date) return dflt;
    if (typeof value === 'boolean') return dflt;
    var text = String(value).trim();
    if (!text) return dflt;
    var m = NUMBER_RE.exec(withoutCommas(text));
    return m === null ? dflt : parseFloat(m[0]);
  }

  /** text with its commas read as parseNumber reads them. A comma is a
   * thousands separator only when exactly three digits follow it and end the
   * number; any other comma between digits is a decimal comma, which crews
   * trained on French-language sheets type as a matter of course. "1,5" used
   * to parse as 15 and "078,7" as 787.
   * @param {string} text
   * @returns {string}
   */
  function withoutCommas(text) {
    if (text.indexOf(',') < 0) return text;
    if (text.indexOf('.') >= 0 && text.lastIndexOf(',') > text.lastIndexOf('.')) {
      return text.replace(/\./g, '').replace(/,/g, '.');
    }
    text = text.replace(/(\d),(?=\d{3}(?!\d))/g, '$1');
    text = text.replace(/(\d),(?=\d)/g, '$1.');
    return text.replace(/,/g, '');
  }

  /* The whole of a cell that is one number, and the units a field sheet
   * writes after a reading: utils.py _WHOLE_NUMBER_RE and _UNIT_SUFFIX_RE. A
   * letter that is not one of the units is a misread rather than a unit: "12O"
   * is 120 with a scanner's letter O, not 12 of something. Ohms are written
   * with the Greek capital omega or with the ohm sign, which a text layer may
   * carry instead. */
  var WHOLE_NUMBER_RE = /^[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?$/;
  var UNIT_SUFFIX_RE =
    /\s*(?:m|cm|mm|min|s|h|hr|%|ohm(?:[-. ]?m)?|[\u03a9\u2126](?:[-.\u00b7]?m)?|m3\/h|l\/s|m\/min)$/i;

  /** Whether a cell is one number and nothing else, bar a unit after it.
   * utils.py is_whole_number. parseNumber is lenient on purpose and takes the
   * first number it finds, which is what reading "80m" needs; it is also
   * what reads a scanner's "12O.4" as 12, so a grader asks this instead.
   * @param {*} value a cell
   * @returns {boolean}
   */
  function isWholeNumber(value) {
    if (value === null || value === undefined || typeof value === 'boolean') return false;
    if (typeof value === 'number') return isFinite(value);
    if (value instanceof Date) return false;
    var text = String(value).trim().replace(UNIT_SUFFIX_RE, '');
    return WHOLE_NUMBER_RE.test(withoutCommas(text));
  }

  /* Each depth may carry a decimal comma, as parseNumber reads one: without
   * it "12,5-30" was read as the 5-30 m interval inside it, and the only
   * trace was an overlap flag that blamed the log. */
  var INTERVAL_RE = /(\d+(?:[.,]\d+)?)\s*(?:-|to)\s*(\d+(?:[.,]\d+)?)/i;

  /** Depths are unsigned, so the hyphen is a range separator, never a minus.
   * A date is never an interval: Excel silently turns "5-10" typed into a
   * General cell into 10 May, and reading that as text yielded a 5 to 2026 m
   * interval, which then placed screens and priced casing against a
   * two-kilometre hole.
   * @param {*} value a cell
   * @returns {number[]|null}
   */
  function parseDepthInterval(value) {
    if (value === null || value === undefined || value instanceof Date) return null;
    var m = INTERVAL_RE.exec(String(value));
    if (!m) return null;
    var top = parseNumber(m[1]), bottom = parseNumber(m[2]);
    if (top === null || bottom === null) return null;
    return bottom < top ? [bottom, top] : [top, bottom];
  }

  /* Every dash a sheet can carry: the hyphen variants, the figure, en, em and
   * horizontal dashes, the true minus sign and the full-width hyphen. */
  var DASH_RE = /[\u2010-\u2015\u2212\ufe58\ufe63\uff0d]/g;

  /** Replace every dash a text cell can carry with the plain hyphen.
   *
   * Word turns "5-10" into "5–10" as the crew types it and the en dash
   * survives the copy into Excel, so a depth interval or a screen range
   * written on a laptop reaches the range patterns as a character they do not
   * list. The row was then dropped in silence and the only trace was an
   * "interval_gap" flag blaming the log for a gap the crew never left. A
   * value that is not text is handed back untouched, so a Date or a number
   * still reaches its own parser as itself.
   * @param {*} value a cell; anything but text is handed back as it is
   */
  function normaliseDashes(value) {
    if (typeof value !== 'string') return value;
    return value.replace(DASH_RE, '-');
  }

  /* A metre unit written against a number ("30 m", "5m", "12 metres"), which
   * the depth interval pattern does not expect between the two depths. */
  var METRE_UNIT_RE = /(\d)\s*(?:met(?:re|er)s?|mtrs?|m)\b\.?/gi;

  /* Drop the metre unit written against each number in a text cell
   * (common.strip_metre_units). "30 m - 40 m" and "5m-10m" reach the
   * interval pattern as "30 - 40" and "5-10"; they used to be skipped with
   * the row's description and strike, and the only trace was a gap flag
   * blaming the log. A value that is not text is handed back untouched. */
  function stripMetreUnits(value) {
    if (typeof value !== 'string') return value;
    return value.replace(METRE_UNIT_RE, '$1');
  }

  /* The deeper end of a depth range written in a header cell, if it is one. */
  function rangeBottom(value) {
    if (typeof value !== 'string') return null;
    var interval = parseDepthInterval(stripMetreUnits(normaliseDashes(cleanText(value))));
    return interval ? interval[1] : null;
  }

  /* Canonical header keys and the label patterns that map to them. */
  var LABEL_PATTERNS = {
    client: ['^client\\b'],
    project: ['^project(?!\\s*ref)'],
    project_ref: ['^project\\s*ref', '^geophysics\\s*ref'],
    community: ['^community\\b', '^village\\b', '^location\\b'],
    chiefdom: ['^chiefdom\\b'],
    district: ['^district\\b'],
    sounding_id: ['^sounding\\s*(number|no)', '^ves\\s*(point|number|no)'],
    date: ['^date\\b'],
    supervisor: ['^field\\s*supervisor', '^test\\s*conducted\\s*by', '^operator\\b',
                 '^supervisor\\b'],
    contractor: ['^(drilling\\s*)?contractor\\b'],
    easting: ['^gps\\s*coordinate\\s*east', '^east(ing)?\\b', '^utm\\s*east'],
    northing: ['^gps\\s*coordinate\\s*north', '^north(ing)?\\b', '^utm\\s*north'],
    utm_zone: ['^utm\\s*zone', '^zone\\b'],
    elevation_m: ['^elevation', '^altitude'],
    array_type: ['^array\\b', '^electrode\\s*(array|configuration)'],
    instrument: ['^instrument\\b', '^equipment\\b'],
    borehole_ref: ['^borehole\\s*/?\\s*ref', '^bh\\s*ref', '^borehole\\s*(number|no)'],
    borehole_depth_m: ['^depth\\s*of\\s*borehole', '^borehole\\s*depth',
                       '^total\\s*depth', '^depth\\b'],
    static_water_level_m: ['^static\\s*water\\s*level', '^swl\\b'],
    pump_setting_m: ['^pump\\s*setting', '^pump\\s*installation\\s*depth'],
    step_length_min: ['^length\\s*of\\s*each\\s*step', '^step\\s*length'],
    test_type: ['^test\\s*type'],
    start_time: ['^time\\b', '^start\\s*time'],
    duration: ['^duration'],
    drilling_method: ['^(drilling\\s*)?method\\b'],
    start_date: ['^(drilling\\s*)?start\\s*date'],
    completion_date: ['^compl(etion)?\\.?\\s*date'],
    status: ['^(bh\\s*)?status'],
    sample_id: ['^sample\\s*(id|number|no|ref)'],
    laboratory: ['^lab(oratory)?\\b'],
    sample_date: ['^sample\\s*date', '^date\\s*sampled'],
    grouting_depth_m: ['^grout(ing)?\\b'],
    drill_rig: ['^drill\\s*rig'],
    installed_screens: ['^screens?\\s*installed', '^installed\\s*screens?',
                        '^screens?\\s*(set|as\\s*built)'],
    /* the casing and riser a pumping test co-pilot writes on its sheet,
     * which set how long casing storage lasts */
    casing_diameter_in: ['^casing\\s*diameter'],
    riser_diameter_in: ['^riser(\\s*pipe)?\\s*diameter'],
  };

  var COMPILED_LABELS = (function () {
    var out = {};
    Object.keys(LABEL_PATTERNS).forEach(function (key) {
      out[key] = LABEL_PATTERNS[key].map(function (p) { return new RegExp(p, 'i'); });
    });
    return out;
  }());

  var NUMERIC_HEADER_KEYS = ['easting', 'northing', 'elevation_m',
    'borehole_depth_m', 'static_water_level_m', 'pump_setting_m',
    'step_length_min', 'grouting_depth_m'];

  /* Header depths a crew writes as a range from the surface ("Grouting:
   * 0-20 m"). The depth is the bottom of the range: read as a number, "0-20"
   * was the 0 at its top, the recorded 20 m grout was lost, and screens were
   * drawn at 10-20 m inside it. */
  var RANGE_BOTTOM_KEYS = ['grouting_depth_m'];

  /** Priority is the pattern index within the key's list: 0 is the most
   * specific wording ("Depth of Borehole"), higher numbers are generic
   * fallbacks ("Depth"). A more specific match later in the sheet may
   * overwrite a generic one.
   * @param {*} text
   * @returns {[string, number]|null}
   */
  function matchLabelPriority(text) {
    var label = cleanText(text).replace(/:+$/, '').trim();
    if (!label) return null;
    /** @type {[string, number]|null} */
    var best = null;
    var keys = Object.keys(COMPILED_LABELS);
    for (var i = 0; i < keys.length; i++) {
      var patterns = COMPILED_LABELS[keys[i]];
      for (var p = 0; p < patterns.length; p++) {
        if (patterns[p].test(label)) {
          if (best === null || p < best[1]) {
            if (p === 0) return [keys[i], 0];
            best = [keys[i], p];
          }
          break;
        }
      }
    }
    return best;
  }

  /**
   * @param {*} text
   * @returns {string|null}
   */
  function matchLabel(text) {
    var m = matchLabelPriority(text);
    return m ? m[0] : null;
  }

  /** Split "Community: Kuntoloh" into label and inline value.
   * @param {*} cellText
   * @returns {[string, string|null]}
   */
  function splitInlineValue(cellText) {
    var text = cleanText(cellText);
    var idx = text.indexOf(':');
    if (idx >= 0) {
      var value = text.slice(idx + 1).trim();
      return [text.slice(0, idx), value || null];
    }
    return [text, null];
  }

  function valueBelow(grid, r, c) {
    if (r + 1 >= grid.length) return null;
    var next = grid[r + 1] || [];
    if (c >= next.length) return null;
    var below = next[c];
    if (below === null || below === undefined || cleanText(below) === '') return null;
    if (typeof below !== 'number') {
      var belowLabel = splitInlineValue(below instanceof Date ? cleanText(below) : String(below));
      if (matchLabel(belowLabel[0])) return null;
    }
    return below;
  }

  /** `raw`, when given, is filled with key -> [label, value]: the label text
   * and the cell value each field was read from. A number loses its unit on
   * the way into the fields ("150 ft" is 150), and the drilling log reader
   * needs both the label's unit ("Total depth (ft)") and the cell's.
   * @param {Grid} grid
   * @param {number} [maxRows]
   * @param {Record<string, Array<*>>} [raw]
   * @returns {Rec}
   */
  function extractHeaderFields(grid, maxRows, raw) {
    var limit = maxRows === undefined ? 30 : maxRows;
    var fields = {}, priorities = {};
    for (var r = 0; r < Math.min(limit, grid.length); r++) {
      var row = grid[r] || [];
      for (var c = 0; c < row.length; c++) {
        var cell = row[c];
        if (cell === null || cell === undefined || typeof cell === 'number') continue;
        var split = splitInlineValue(cell instanceof Date ? cleanText(cell) : String(cell));
        var matched = matchLabelPriority(split[0]);
        if (!matched) continue;
        var key = matched[0], priority = matched[1];
        if (key in fields && (priorities[key] === undefined ? 99 : priorities[key]) <= priority) {
          continue;
        }
        var value = split[1];
        if (value === null) {
          for (var cc = c + 1; cc < Math.min(c + 8, row.length); cc++) {
            var nxt = row[cc];
            if (nxt !== null && nxt !== undefined && cleanText(nxt) !== '') {
              /* Stop if the neighbouring cell is itself a label (with or
               * without its own inline value). */
              if (typeof nxt !== 'number') {
                var nxtLabel = splitInlineValue(nxt instanceof Date ? cleanText(nxt) : String(nxt));
                if (matchLabel(nxtLabel[0])) break;
              }
              value = nxt;
              break;
            }
          }
        }
        if (value === null || value === undefined) {
          /* A columnar header block - labels across one row, values in the
           * row beneath - used to parse to nothing at all. The cell below is
           * taken only when it is not itself a label, so the stacked template
           * layout (label over label) is unaffected. */
          value = valueBelow(grid, r, c);
        }
        if (value === null || value === undefined) continue;
        if (NUMERIC_HEADER_KEYS.indexOf(key) >= 0) {
          var number = RANGE_BOTTOM_KEYS.indexOf(key) >= 0 ? rangeBottom(value) : null;
          if (number === null) number = parseNumber(value);
          if (number !== null) {
            fields[key] = number; priorities[key] = priority;
            if (raw) raw[key] = [split[0], value];
          }
        } else {
          fields[key] = cleanText(headerDateText(value));
          priorities[key] = priority;
          if (raw) raw[key] = [split[0], value];
        }
      }
    }
    return fields;
  }

  /**
   * @param {Rec} fields what extractHeaderFields returns
   * @param {string} [source]
   */
  function siteFromFields(fields, source) {
    /* The zone cell is read with parseUtmZone, which takes the number that
     * follows a label and refuses anything naming no single zone. Read with
     * parseNumber, the value cell "0708958" - an easting the header matcher
     * had taken for the zone - became a zone of 708958. */
    return {
      client: fields.client || '', project: fields.project || '',
      community: fields.community || '', chiefdom: fields.chiefdom || '',
      district: fields.district || '', country: 'Sierra Leone',
      project_ref: fields.project_ref || '',
      easting: fields.easting === undefined ? null : fields.easting,
      northing: fields.northing === undefined ? null : fields.northing,
      utm_zone: parseUtmZone(fields.utm_zone),
      elevation_m: fields.elevation_m === undefined ? null : fields.elevation_m,
      date: fields.date === undefined ? '' : String(fields.date),
      supervisor: fields.supervisor || '', contractor: fields.contractor || '',
      source: source || '',
    };
  }

  /**
   * @param {Array<*>|null} [row]
   * @returns {string[]}
   */
  function rowText(row) {
    return (row || []).map(function (c) { return cleanText(c).toLowerCase(); });
  }

  /* --- VES sheets ---------------------------------------------------------- */

  var MN_HALF_RE = /mn\s*\/\s*2/;

  /* "Resistance (ohm)", "R (ohm)", "V/I", "dV/I": a measured resistance */
  var RESISTANCE_RE = /resistance|^r\s*\(|v\s*\/\s*i/;
  /* The unit of a resistivity, ohm-metres however a sheet writes it: "ohm-m",
   * "ohm.m", "ohm m", "ohmm", "Ωm", "Ω·m", "ohm-metre". Only a
   * resistivity is in ohm-metres, so a column headed "R (ohm-m)" is one,
   * whatever its name says; such a column used to be read as V/I and
   * multiplied by K. The same pattern as ingestion/ves.py _RESISTIVITY_UNIT_RE. */
  var RESISTIVITY_UNIT_RE =
    /(?:ohm|ω)\s*[-.·⋅•*]?\s*m(?:et(?:er|re)s?)?(?![a-z])/;

  /* The array a sheet names, wherever on the sheet it names it: the title of a
   * template ("SCHLUMBERGER ARRAY VES FIELD DATA"), the array field itself, or
   * a note. "Wenner alpha" and "half-Schlumberger" are the same two arrays. */
  var WENNER_RE = /wenner/;
  var SCHLUMBERGER_RE = /schlum/;

  /* "a" is the whole name of the Wenner spacing, so the column header is short
   * and the reader has to accept the few ways a crew writes it out. */
  var WENNER_A_HEADERS = [
    'a', 'a (m)', 'a(m)', 'a m', 'a, m', 'a (metres)', 'a (meters)',
    'a-spacing', 'a-spacing (m)', 'a spacing', 'a spacing (m)',
    'spacing a', 'spacing a (m)', 'wenner a', 'wenner a (m)', 'a (wenner)',
  ];

  /* A Wenner array is A M N B at equal spacing a, so AB = 3a and a Wenner sheet
   * that tabulates AB/2 has written 1.5 a in that column. */
  var WENNER_AB2_PER_A = 1.5;

  /* The array a piece of sheet text names, or null.
   *
   * null covers both the text that names no array and the text that names
   * two: an unfilled "Schlumberger / Wenner" template choice settles nothing,
   * and reading it as either would be a guess. */
  function arrayNamedIn(text) {
    var lowered = String(text || '').toLowerCase();
    var wenner = WENNER_RE.test(lowered);
    var schlumberger = SCHLUMBERGER_RE.test(lowered);
    if (wenner === schlumberger) return null;
    return wenner ? 'wenner' : 'schlumberger';
  }

  /* The array the wording above the data table names, if only one is named. */
  function arrayNamedAboveTable(grid, headerRow) {
    var found = [];
    for (var r = 0; r < headerRow && r < grid.length; r++) {
      var texts = rowText(grid[r]);
      for (var c = 0; c < texts.length; c++) {
        if (WENNER_RE.test(texts[c]) && found.indexOf('wenner') < 0) {
          found.push('wenner');
        }
        if (SCHLUMBERGER_RE.test(texts[c]) && found.indexOf('schlumberger') < 0) {
          found.push('schlumberger');
        }
      }
    }
    return found.length === 1 ? found[0] : null;
  }

  /* The array a sheet was run with, and the flags reading it raised.
   *
   * The forward model, the inversion, the splice and the curve plot all branch
   * on array_type, but the reader never looked at the sheet for it beyond
   * copying out the array field: a Wenner sounding had no ingestion path, and
   * a Wenner sheet headed AB/2 was inverted with AB/2 for the spacing a
   * (ROADMAP data-ingestion-11). That is wrong by tens of percent and nothing
   * downstream can notice.
   *
   * The sheet is asked in the order its answers are worth trusting: the array
   * field of the header block, then any other wording above the table (a
   * template title is boilerplate, so it only speaks when the field is
   * silent), then the table's own columns - a spacing column headed "a" is the
   * Wenner spacing, and an MN column is the Schlumberger one. Where the sheet
   * settles nothing, or contradicts itself, the Schlumberger default stands
   * and a flag says what was assumed and why, because an assumption made in
   * silence is how the wrong array reaches a client report. */
  function detectArray(grid, headerRow, cols, fields) {
    /** @type {Rec[]} */
    var flags = [];
    var declaredText = cleanText(fields.array_type);
    var declared = arrayNamedIn(declaredText);
    var named = declared !== null ? declared
      : arrayNamedAboveTable(grid, headerRow);
    var fromColumns = ('a' in cols) ? 'wenner'
      : (('mn' in cols) || ('mn_half' in cols)) ? 'schlumberger' : null;

    var conflicted = named === 'schlumberger' && fromColumns === 'wenner';
    var arrayType = conflicted ? 'schlumberger'
      : (named || fromColumns || 'schlumberger');

    if (conflicted) {
      flags.push({ level: 'warning', code: 'array_type_conflict',
        message: 'The sheet names the Schlumberger array but heads its ' +
          'spacing column "a", which is the Wenner spacing; the two readings ' +
          'of the same column differ by half again. The sounding was read as ' +
          'Schlumberger, with that column taken as AB/2. Confirm the array ' +
          'with the field crew before the model is used.' });
    } else if (declaredText && declared === null) {
      flags.push({ level: 'warning', code: 'array_type_unrecognised',
        message: "The sheet's array field reads " + '"' + declaredText +
          '", which does not name one of the two arrays this toolkit models ' +
          '(Schlumberger and Wenner); the sounding was read as ' +
          arrayType.charAt(0).toUpperCase() + arrayType.slice(1) +
          '. Confirm the array with the field crew: the wrong forward model ' +
          'is wrong by tens of percent.' });
    } else if (named === null && fromColumns === null) {
      flags.push({ level: 'warning', code: 'array_type_assumed',
        message: 'The sheet does not say which electrode array was used, and ' +
          'its columns do not settle it either: there is no MN column, which ' +
          'a Schlumberger sheet carries, and no "a" column, which a Wenner ' +
          "sheet carries. Schlumberger was assumed, as the toolkit's " +
          'default. Confirm the array with the field crew: a Wenner sounding ' +
          'inverted as Schlumberger is wrong by tens of percent and nothing ' +
          'further down the chain can notice.' });
    } else if (named === null && fromColumns === 'wenner') {
      flags.push({ level: 'info', code: 'array_type_inferred',
        message: 'No array is named on the sheet; its spacing column is ' +
          'headed "a", which is the Wenner spacing, so the sounding was read ' +
          'as Wenner.' });
    }
    return { array_type: arrayType, flags: flags };
  }

  function findVesDataHeader(grid) {
    for (var r = 0; r < grid.length; r++) {
      var cols = vesReadingColumns(grid[r]);
      if (('ab2' in cols || 'a' in cols) &&
          ('rho' in cols || 'resistance' in cols)) {
        return { row: r, cols: cols };
      }
    }
    return null;
  }

  /** What each heading of a VES table names, by the rules the reader reads a
   * header row with (ves.py reading_columns), the last column of a kind
   * winning. The extraction fills the VES template with it, so a sheet's
   * columns are placed by the same rules that read the template back.
   * @param {Array<*>} headings
   * @returns {Record<string, number>}
   */
  function vesReadingColumns(headings) {
    var texts = rowText(headings || []);
    /** @type {Record<string, number>} */
    var cols = {};
    for (var c = 0; c < texts.length; c++) {
      var t = texts[c];
      if (!t) continue;
      if (t.indexOf('ab/2') >= 0 || t === 'ab2' || t.indexOf('ab / 2') >= 0) {
        cols.ab2 = c;
      } else if (WENNER_A_HEADERS.indexOf(t) >= 0) {
        /* The Wenner spacing column, headed "a" or "a (m)", meant nothing to
         * the reader at all, so a Wenner sheet was dropped whole as having
         * no data table (ROADMAP data-ingestion-11) */
        cols.a = c;
      } else if (t.indexOf('mn') === 0 && MN_HALF_RE.test(t)) {
        /* half-MN first, and tolerant of the spaces a typed header carries:
         * "MN / 2 (m)" does not contain the literal "/2", so it would fall
         * through to the full-MN branch and halve every potential spacing */
        cols.mn_half = c;
      } else if (t.indexOf('mn') === 0) {
        cols.mn = c;
      } else if (RESISTIVITY_UNIT_RE.test(t)) {
        /* a column in ohm-metres is a resistivity, before the resistance
         * test reads "R (" or "resistance" in its name */
        cols.rho = c;
      } else if (RESISTANCE_RE.test(t)) {
        /* a sheet that records V/I (a resistance, in ohms) is not a
         * resistivity sheet: "R (ohm)" used to match the "ohm" test below
         * and every reading came through as a resistivity of 0.9 */
        cols.resistance = c;
      } else if (t.indexOf('resistivity') >= 0 || t.indexOf('rho') === 0 ||
                 t.indexOf('ohm') >= 0 || t.indexOf('apparent') >= 0 ||
                 t.indexOf('\u03c1') >= 0 || t.indexOf('\u03c9') >= 0) {
        cols.rho = c;
      } else if (['k', 'k (m)', 'k(m)', 'geometric factor'].indexOf(t) >= 0) {
        cols.k = c;
      } else if (['no.', 'no', 'reading', 'n'].indexOf(t) >= 0) {
        cols.no = c;
      }
    }
    return cols;
  }

  /**
   * @param {Grid} grid
   * @param {string} [source]
   * @param {string} [sheetName]
   * @returns {Sounding|null}
   */
  function soundingFromGrid(grid, source, sheetName) {
    return soundingOrReason(grid, source, sheetName)[0];
  }

  /** [sounding | null, reason]: the sounding on a sheet, or why there is none.
   * A sheet the reader could not use was dropped without a word, so a
   * three-sheet workbook with one mislabelled sheet came back as two
   * soundings and nothing said so.
   * @param {Grid} grid
   * @param {string} [source]
   * @param {string} [sheetName]
   * @returns {[Sounding|null, string]}
   */
  function soundingOrReason(grid, source, sheetName) {
    var fields = extractHeaderFields(grid);
    var site = siteFromFields(fields, source);
    var located = findVesDataHeader(grid);
    if (!located) {
      return [null, 'no data table found: a header row needs an AB/2 column ' +
        '(or the Wenner spacing column "a") and an apparent-resistivity ' +
        'column (Resistivity, Rho, ohm.m, \u03c1 or \u03a9)'];
    }
    var cols = located.cols;

    var detected = detectArray(grid, located.row, cols, fields);
    var arrayType = detected.array_type;
    var isWenner = arrayType.indexOf('wenner') === 0;

    var ab2 = [], mn = [], rho = [], flags = detected.flags;
    var mnIsHalf = !('mn' in cols) && ('mn_half' in cols);
    var mnCol = 'mn' in cols ? cols.mn : cols.mn_half;
    var fromResistance = !('rho' in cols);
    var valueCol = fromResistance ? cols.resistance : cols.rho;
    var kCol = cols.k;
    /* The spacing column. A Wenner sheet with its own "a" column is read from
     * it as it stands; anything else is read from AB/2, which on a Wenner
     * sheet is 1.5 a and has to be converted below. */
    var spacingCol, wennerFromAb2;
    if (isWenner && ('a' in cols)) {
      spacingCol = cols.a; wennerFromAb2 = false;
    } else if ('ab2' in cols) {
      spacingCol = cols.ab2; wennerFromAb2 = isWenner;
    } else {
      spacingCol = cols.a; wennerFromAb2 = false;
    }
    var blankRun = 0;
    /** @type {number[]} AB/2 of resistances K could not convert */
    var kUndefined = [];

    for (var r = located.row + 1; r < grid.length; r++) {
      var row = grid[r] || [];
      var a = spacingCol < row.length ? parseNumber(row[spacingCol]) : null;
      var rr = valueCol < row.length ? parseNumber(row[valueCol]) : null;
      var m = (mnCol !== undefined && mnCol < row.length) ? parseNumber(row[mnCol]) : null;
      if (a !== null && wennerFromAb2) {
        /* The sheet is Wenner but tabulates AB/2, and AB = 3a, so the column
         * holds 1.5 a. Taken for the spacing a, as it used to be (ROADMAP
         * data-ingestion-11), every reading sits at half again its true
         * spacing and the whole curve shifts along the depth axis. Convert
         * once, here, so ab2 means what the forward model, the inversion and
         * the plots take it to mean for a Wenner sounding: the spacing a. */
        a = a / WENNER_AB2_PER_A;
      }
      if (fromResistance && a !== null && rr !== null) {
        /* rho_a = K x (dV/I): use the sheet's own K column when it has one,
         * otherwise the geometric factor of the array the sheet was run with.
         * The Wenner factor is 2 pi a and needs no MN, which is as well: a
         * Wenner sheet does not carry an MN column, so the Schlumberger
         * factor left K unknown and the row was dropped. */
        var k = (kCol !== undefined && kCol < row.length) ? parseNumber(row[kCol]) : null;
        if (k === null && isWenner) {
          k = geometricFactor('wenner', { a: a });
        } else if (k === null) {
          var spacing = (m !== null && mnIsHalf) ? 2.0 * m : m;
          /* K is defined only for 0 < MN/2 < AB/2, and geometricFactor throws
           * outside that: one mistyped spacing on a resistance sheet used to
           * throw out of the reader and lose every sheet of the workbook. The
           * row is left out and flagged instead. */
          if (spacing !== null && spacing / 2.0 > 0 && spacing / 2.0 < a) {
            k = geometricFactor('schlumberger', { ab2: a, mn: spacing });
          } else if (spacing !== null) {
            kUndefined.push(a);
          }
        }
        rr = k ? k * rr : null;
      }
      if (a === null && rr === null) {
        var fullyBlank = row.every(function (v) {
          return v === null || v === undefined || cleanText(v) === '';
        });
        /* Tolerate an isolated blank spacer row inside the table - field sheets
         * routinely leave one at a Schlumberger MN segment change. Only two
         * consecutive blank rows mark the true end, so the deep branch after a
         * spacer is kept. */
        if (ab2.length && fullyBlank) {
          blankRun += 1;
          if (blankRun >= 2) break;
        }
        continue;
      }
      if (a === null || rr === null) continue;
      blankRun = 0;
      if (m !== null && mnIsHalf) m = 2.0 * m;
      ab2.push(a);
      mn.push(m === null ? NaN : m);
      rho.push(rr);
    }
    if (!ab2.length) {
      return [null, 'the data table has a header but no numeric rows; if the ' +
        'cells hold formulas, open the workbook in Excel and save it so the ' +
        'values are stored'];
    }
    if (wennerFromAb2) {
      flags.push({ level: 'info', code: 'wenner_spacing_from_ab2',
        message: 'The sheet is a Wenner sounding tabulated as AB/2. The ' +
          'Wenner array has AB = 3a, so each spacing was read as a = two ' +
          'thirds of the tabulated AB/2, which is the spacing the Wenner ' +
          'geometric factor and forward model take.' });
    }
    if (isWenner) {
      /* A Wenner array keeps MN equal to a and reads each spacing once. A
       * Schlumberger sheet with only its array field changed to "Wenner" was
       * read as Wenner, every spacing divided by 1.5, with nothing but
       * information notes, although its MN column and the repeated AB/2 at
       * each MN change are things a Wenner array cannot have. numpy's
       * isclose(rtol=0.01) is the tolerance on MN = a. */
      var reasons = [];
      var mnOff = mn.some(function (v, i) {
        return isFinite(v) && !(Math.abs(v - ab2[i]) <= 1e-8 + 0.01 * Math.abs(ab2[i]));
      });
      if (mnOff) reasons.push('its MN column holds spacings other than a');
      var counts = {}, repeated = 0;
      ab2.forEach(function (v) { counts[v] = (counts[v] || 0) + 1; });
      Object.keys(counts).forEach(function (v) { if (counts[v] > 1) repeated += 1; });
      if (repeated) reasons.push('it repeats ' + plural(repeated, 'spacing'));
      if (reasons.length) {
        flags.push({ level: 'warning', code: 'array_type_wenner_contradicted',
          message: 'The sounding was read as Wenner, as the sheet has it, but ' +
            reasons.join(' and ') + '. A Wenner array keeps MN equal to the ' +
            'spacing a and reads each spacing once, so these are the marks of a ' +
            'Schlumberger sounding. Confirm the array with the field crew: the ' +
            'wrong forward model is wrong by tens of percent.' });
      }
    }
    if (fromResistance) {
      flags.push({ level: 'info', code: 'rho_computed_from_resistance',
        message: 'The sheet records a resistance (V/I), not a resistivity; ' +
          'apparent resistivity was computed as K x R from the electrode ' +
          'spacings' + (kCol === undefined ? '' : " and the sheet's K column") + '.' });
    }

    var soundingId = String(fields.sounding_id || sheetName || 'VES 1') || 'VES 1';
    /** @type {Sounding} */
    var sounding = {
      site: site, sounding_id: soundingId,
      ab2: ab2, mn: mn, rho_app: rho,
      array_type: arrayType,
      instrument: fields.instrument || '', source: String(source || ''), flags: [],
    };

    if (rho.some(function (v) { return v <= 0; })) {
      flags.push({ level: 'error', code: 'nonpositive_resistivity',
        message: 'Apparent resistivity values must be positive.', context: soundingId });
    }
    /* A spacing of 0 is a formula over a blank cell or a placeholder row; the
     * reading is kept here, as read, and the inversion leaves it out. */
    var badSpacings = ab2.filter(function (v) { return !(v > 0); }).length;
    if (badSpacings) {
      flags.push({ level: 'warning', code: 'nonpositive_spacing',
        message: phrase('ves.nonpositive_spacing', { n: badSpacings }),
        context: soundingId });
    }
    if (kUndefined.length) {
      flags.push({ level: 'warning', code: 'k_undefined',
        message: phrase('ves.k_undefined', { n: kUndefined.length,
          spacings: andJoin(kUndefined.map(function (v) { return formatG(v); })) }),
        context: soundingId });
    }
    for (var d = 1; d < ab2.length; d++) {
      if (ab2[d] - ab2[d - 1] < 0) {
        flags.push({ level: 'warning', code: 'ab2_not_sorted',
          message: 'AB/2 values are not in increasing order; check the sheet.',
          context: soundingId });
        break;
      }
    }
    for (var mk = 0; mk < mn.length; mk++) {
      if (isFinite(mn[mk]) && ab2[mk] <= mn[mk] / 2) {
        flags.push({ level: 'warning', code: 'mn_exceeds_ab',
          message: 'MN/2 is not smaller than AB/2 for some readings.',
          context: soundingId });
        break;
      }
    }
    var seen = {}, dup = 0;
    ab2.forEach(function (v) { seen[v] = (seen[v] || 0) + 1; });
    Object.keys(seen).forEach(function (v) { if (seen[v] > 1) dup += 1; });
    if (dup) {
      /* The splice merges a repeated spacing by geometric mean only on a
       * Schlumberger sounding with more than one MN segment. A Wenner sheet, or
       * one with no MN change recorded, is fitted reading by reading, and its
       * flags used to say the pair was merged at an MN change all the same. */
      var merged = !isWenner && soundingSegments(sounding).length > 1;
      flags.push({ level: 'info', code: 'segment_overlap',
        message: phrase(merged ? 'ves.segment_overlap' : 'ves.repeat_reading', { n: dup }),
        context: soundingId });
      var discrepant = overlapDiscrepancies(ab2, rho);
      if (discrepant.length) {
        flags.push({ level: 'warning', code: 'segment_overlap_discrepancy',
          message: phrase(merged ? 'ves.overlap_discrepancy' : 'ves.repeat_discrepancy', {
            percent: (OVERLAP_DISCREPANCY_RATIO - 1) * 100, pairs: discrepant.join('; ') }),
          context: soundingId });
      }
    }
    sounding.flags = flags;
    return [sounding, ''];
  }

  /* Readings at one AB/2 taken with two MN spacings should agree closely; a
   * ratio beyond this is not the segment shift the splice is built for. */
  var OVERLAP_DISCREPANCY_RATIO = 1.2;

  /* Every spacing read more than once: the usable readings there, and the
   * largest over the smallest. */
  function overlaps(ab2, rho) {
    var unique = ab2.slice().sort(function (a, b) { return a - b; })
      .filter(function (v, k, a) { return k === 0 || v !== a[k - 1]; });
    var out = [];
    unique.forEach(function (value) {
      var readings = [];
      for (var k = 0; k < ab2.length; k++) {
        if (ab2[k] === value && isFinite(rho[k]) && rho[k] > 0) readings.push(rho[k]);
      }
      if (readings.length < 2) return;
      out.push({ value: value, readings: readings,
        ratio: Math.max.apply(null, readings) / Math.min.apply(null, readings) });
    });
    return out;
  }

  /** ingestion/ves.py overlap_ratios: [AB/2, ratio] at every MN overlap,
   * flagged or not. The range of models reads the measured disagreement at
   * each overlap as part of that reading's error, so the flag and the error
   * model judge an MN change from the same two numbers.
   * @param {number[]} ab2
   * @param {number[]} rho
   * @returns {number[][]}
   */
  function overlapRatios(ab2, rho) {
    return overlaps(ab2, rho).map(function (o) { return [o.value, o.ratio]; });
  }

  /** The overlap pairs whose readings disagree by more than the ratio, as
   * "AB/2 40 m: 156.1 and 78.7 ohm-m (ratio 1.98)". The VES co-pilot asks
   * the same question of each pair at the peg, so the field and the office
   * judge an MN change by one test.
   * @param {number[]} ab2
   * @param {number[]} rho
   * @returns {string[]}
   */
  function overlapDiscrepancies(ab2, rho) {
    var out = [];
    overlaps(ab2, rho).forEach(function (overlap) {
      var value = overlap.value, readings = overlap.readings, ratio = overlap.ratio;
      if (ratio > OVERLAP_DISCREPANCY_RATIO) {
        /* the pair the ratio is of, in field order: with three readings at
         * one spacing the first two can agree while the third is the one out */
        var hi = readings.indexOf(Math.max.apply(null, readings));
        var lo = readings.indexOf(Math.min.apply(null, readings));
        var ends = [Math.min(hi, lo), Math.max(hi, lo)];
        out.push('AB/2 ' + formatG(value) + ' m: ' + formatG(readings[ends[0]]) + ' and ' +
          formatG(readings[ends[1]]) + ' ohm-m (ratio ' + pyFixed(ratio, 2) + ')');
      }
    });
    return out;
  }

  /* One worksheet per sounding. */
  /** skipped, when given, receives one warning flag per sheet that yielded
   * no sounding, naming the sheet and the reason
   * @param {Array<{name: string, rows: Grid}>} sheets
   * @param {string} [source]
   * @param {Rec[]} [skipped] receives a flag for each sheet that held no sounding
   * @returns {Sounding[]}
   */
  function readVesSheets(sheets, source, skipped) {
    var out = [], titles = [];
    sheets.forEach(function (sheet) {
      var pair = soundingOrReason(sheet.rows, source || '', sheet.name);
      if (pair[0]) {
        out.push(pair[0]);
        titles.push(sheet.name);
      } else if (skipped) {
        skipped.push({ level: 'warning', code: 'sheet_skipped',
          message: "Sheet '" + sheet.name + "' was skipped: " + pair[1] + '.' });
      }
    });
    flagDuplicateIds(out, titles);
    return out;
  }

  /* ingestion/ves.py _flag_duplicate_ids: a sheet copied for the next point
   * and never renumbered reads as the same point in every table, figure and
   * ranking, and nothing downstream can tell the two apart by name. */
  function flagDuplicateIds(soundings, titles) {
    var firstSheet = {};
    soundings.forEach(function (sounding, i) {
      var sid = sounding.sounding_id;
      if (Object.prototype.hasOwnProperty.call(firstSheet, sid)) {
        sounding.flags.push({ level: 'warning', code: 'duplicate_sounding_id',
          message: "Sheet '" + titles[i] + "' carries the sounding number '" + sid +
            "', which sheet '" + firstSheet[sid] + "' already uses. A sheet copied " +
            'without renumbering reads as the same point in every table, figure ' +
            'and ranking; give each sounding its own number before the results ' +
            'are used.',
          context: sid });
      } else {
        firstSheet[sid] = titles[i];
      }
    });
  }

  /* --- drilling logs -------------------------------------------------------- */

  /* The international foot, in metres, exactly. */
  var FOOT_M = 0.3048;

  /* The codes this reader raises when a cell could not be read: a row
   * dropped, or a value refused, for its form or its unit
   * (ingestion/drilling.py UNREADABLE_CODES). The readiness gate reads them,
   * so "every reading carried a unit the toolkit could read" is not said of
   * a log that lost one; they are kept here, beside the reader that raises
   * them. */
  var DRILLING_UNREADABLE = ['interval_read_as_date', 'interval_unreadable',
    'depth_unit_ambiguous', 'water_strike_unreadable', 'diameter_implausible'];

  /* Those, and a strike that was read but refused because it lies below the
   * bottom of the hole: every code that means the log as read is not the
   * log the crew wrote, so the gate does not call it complete
   * (REFUSAL_CODES). */
  var DRILLING_REFUSALS = DRILLING_UNREADABLE.concat(['water_strike_below_total_depth']);

  /* A foot written against a number: "20 ft", "20ft.", "20 feet", "20'", and
   * the curly apostrophe and the prime a word processor puts in its place.
   * Two marks together are inches, which no depth is written in. */
  var FOOT_UNIT_RE = /(\d)\s*(?:feet\b|foot\b|ft\b\.?|['’′](?!['’′]))/gi;

  /* The length unit a column header or a field's label names: "Depth
   * interval (ft)", "Total depth (m)". A lone apostrophe in brackets is
   * feet. */
  var HEADER_FEET_RE = /\b(?:feet|foot|ft)\b|\(\s*['’′]\s*\)/i;
  var HEADER_METRE_RE = /\b(?:met(?:re|er)s?|mtrs?|m)\b/i;
  var RATE_FEET_RE = /feet|foot|ft/i;

  /** 'ft', 'm', 'both' or null: the length unit a header names. A header
   * naming both ("Depth (m/ft)") says nothing about a bare number under it,
   * and a number under it with no unit of its own is refused.
   * @param {*} header a header cell
   * @returns {string|null}
   */
  function headerLengthUnit(header) {
    var text = cleanText(header);
    var feet = HEADER_FEET_RE.test(text), metres = HEADER_METRE_RE.test(text);
    if (feet && metres) return 'both';
    return feet ? 'ft' : (metres ? 'm' : null);
  }

  /* A cell with the feet and metre units against its numbers dropped, and
   * the units it carried: [text, units]. A value that is not text is handed
   * back as it is. */
  function lengthUnits(value) {
    if (typeof value !== 'string') return [value, []];
    var units = [];
    var text = normaliseDashes(value);
    var stripped = text.replace(FOOT_UNIT_RE, '$1');
    if (stripped !== text) units.push('ft');
    var metric = stripMetreUnits(stripped);
    if (metric !== stripped) units.push('m');
    return [metric, units];
  }

  /* The unit a depth is read in, and why not when it cannot be: [unit, why].
   * The cell's own unit first, then its column header's (or its field's
   * label's), then the sheet's: the one unit every depth and rate unit the
   * sheet names agrees on, or metres, the template's unit, where it names
   * none. unit is null and why a key of drilling.ambiguous_why when the
   * depth cannot be read. */
  function resolveUnit(cellUnits, column, sheet) {
    if (cellUnits.length > 1) return [null, 'cell'];
    if (cellUnits.length) return [cellUnits[0], ''];
    if (column === 'both') return [null, 'header'];
    if (column) return [column, ''];
    if (sheet === null) return [null, 'sheet'];
    return [sheet, ''];
  }

  /* A depth in `unit` in metres; feet are kept to the centimetre, as a
   * converted bit size is kept to two decimals. */
  function inMetres(value, unit) {
    return unit === 'ft' ? pyRound(value * FOOT_M, 2) : value;
  }

  /* Whether a cell in the interval column was meant as a depth interval. A
   * cell of numbers and separators with nothing else in it ("30 -", "30 40")
   * is a row the crew logged and this parser could not read, and it is
   * flagged. A note under the table ("Water strike 1: 18 m") has words in it
   * and is not a row at all. */
  function readsAsInterval(value) {
    if (value === null || value === undefined || typeof value === 'boolean') return false;
    if (value instanceof Date) return false;
    if (typeof value === 'number') return true;
    var text = String(lengthUnits(cleanText(value))[0])
      .replace(/\b(?:to|from)\b/gi, ' ');
    return /\d/.test(text) && !/[a-z]/i.test(text);
  }

  function findLogHeader(grid) {
    for (var r = 0; r < grid.length; r++) {
      var texts = rowText(grid[r]);
      /** @type {Record<string, number>} */
      var cols = {};
      for (var c = 0; c < texts.length; c++) {
        var t = texts[c];
        if (!t) continue;
        if ((t.indexOf('depth') >= 0 && t.indexOf('interval') >= 0) ||
            t.indexOf('depth /') === 0) {
          cols.interval = c;
        } else if (t.indexOf('depth') === 0 && !('interval' in cols)) {
          if (!('interval' in cols)) cols.interval = c;
        } else if (t.indexOf('from') === 0) {
          if (!('from_time' in cols)) cols.from_time = c;
        } else if (t.indexOf('to') === 0) {
          if (!('to_time' in cols)) cols.to_time = c;
        } else if (t.indexOf('penetration') >= 0) {
          cols.rate = c;
        } else if (t.indexOf('sample') >= 0 || t.indexOf('litholog') >= 0 ||
                   t.indexOf('description') >= 0) {
          if (!('description' in cols)) cols.description = c;
        } else if (t.indexOf('diameter') >= 0 || t.indexOf('bit') >= 0) {
          if (!('diameter' in cols)) cols.diameter = c;
        } else if (t.indexOf('strike') >= 0) {
          cols.strike = c;
        }
      }
      if ('interval' in cols) return { row: r, cols: cols };
    }
    return null;
  }

  var SCREEN_RANGE_SOURCE = '(\\d+(?:\\.\\d+)?)\\s*(?:-|–|to)\\s*(\\d+(?:\\.\\d+)?)';

  /* A clock time carries a colon or an "h" between the hour and the minutes
   * ("14:30", "14h30"). A decimal point is deliberately not a clock separator
   * here: "8.50" in a strike note is a depth far more often than it is ten to
   * nine, and reading it as a time would lose the strike.
   *
   * A clock time is written with no space inside it. "Water strike 1: 12 m,
   * water strike 2: 30 m" numbers its strikes with a colon and a space, and a
   * pattern that allowed the space took "1: 12" and "2: 30" for times and
   * recorded no strike at all, without a flag. */
  var CLOCK_TIME_RE = /\b\d{1,2}[:h]\d{2}\b(?:\s*(?:am|pm|hrs?))?|\b\d{3,4}\s*(?:hrs?|hours?)\b/gi;

  /* A water level written beside a strike ("Water strike at 18 m; rest water
   * level 4.5 m") is not a strike. Its number was read as one, so the log
   * recorded strikes at 4.5 m and 18 m and the design basis explained why the
   * 4.5 m strike was not screened. */
  var WATER_LEVEL_RE = new RegExp('\\b(?:s\\.?w\\.?l|r\\.?w\\.?l|' +
    '(?:rest(?:ing)?|static|standing)\\s+(?:water\\s+)?level|water\\s+level)\\b' +
    '\\.?[^\\d;,.]*?\\d+(?:[.,]\\d+)?\\s*' +
    '(?:met(?:re|er)s?\\b|m\\b|feet\\b|foot\\b|ft\\b\\.?)?', 'gi');

  /* One depth, or a list of them sharing the unit written after the last
   * ("12, 18 and 30 m"), in metres. The lookahead keeps the "m" of a rate
   * ("0.5 m/min") from reading as a depth in metres. */
  var DEPTH_LIST_RE = new RegExp(
    /* A slash is not a list separator here. "1/2 m" is half a metre and
     * "12/30" is as likely a date as a pair, and both used to come out as
     * two strikes - which is the invention this parser exists to stop. */
    '(?:\\d+(?:[.,]\\d+)?\\s*(?:,|&|\\+|and\\b)\\s*)*' +
    '\\d+(?:[.,]\\d+)?\\s*(?:met(?:re|er)s?|m)\\b(?!\\s*/)', 'gi');

  /* The same in feet ("45 ft", "45 and 90 ft", "45'"), converted to metres.
   * A strike written "at 90 ft" used to be the bare number 90 and recorded
   * as a strike at 90 m. */
  var FEET_LIST_RE = new RegExp(
    '(?:\\d+(?:[.,]\\d+)?\\s*(?:,|&|\\+|and\\b)\\s*)*' +
    '\\d+(?:[.,]\\d+)?\\s*(?:feet\\b|foot\\b|ft\\b\\.?|[\'’′](?![\'’′]))(?!\\s*/)', 'gi');

  var NUMBER_TOKEN_RE = /\d+(?:[.,]\d+)?/g;

  /* The unit a diameter cell carries, if it carries one at all. Bit sizes are
   * quoted in halves and eighths of an inch, so the number may be a whole and
   * a fraction ("6 1/2 in"): groups are number, numerator, denominator, unit. */
  var DIAMETER_UNIT_RE = new RegExp('(\\d+(?:[.,]\\d+)?)' +
    '(?:\\s*(\\d+)\\s*/\\s*(\\d+))?\\s*' +
    '(millimet(?:re|er)s?|mms?|centimet(?:re|er)s?|cms?' +
    '|inch(?:es)?|in|\'\'|"|”|″)(?![a-z])', 'gi');

  /* The unit a penetration rate cell carries: metres per minute or hour, or
   * the time per metre a driller times with a stopwatch and writes the other
   * way up. The order of the alternatives is load-bearing.
   *
   * A rig sheet in feet times the foot ("4 min/ft") or quotes feet a minute
   * ("1.5 ft/min"). Neither matched, so "4 min/ft" fell through to the bare
   * number and was recorded as 4 m/min, some 52 times too fast; the foot is
   * a length here like the metre, and the rate is converted from it. */
  var METRE_SOURCE = '(?:met(?:re|er)s?|m|feet|foot|ft)';
  var RATE_UNITS_SOURCE = METRE_SOURCE + '\\s*(?:/|per)\\s*min(?:ute)?s?' +
    '|' + METRE_SOURCE + '\\s*(?:/|per)\\s*(?:hrs?|hours?|h)' +
    '|min(?:ute)?s?\\s*(?:/|per)\\s*' + METRE_SOURCE +
    '|sec(?:ond)?s?\\s*(?:/|per)\\s*' + METRE_SOURCE +
    '|s\\s*(?:/|per)\\s*' + METRE_SOURCE;
  var RATE_UNIT_RE = new RegExp('(\\d+(?:[.,]\\d+)?)\\s*(' + RATE_UNITS_SOURCE +
    ')(?![a-z])', 'gi');

  /* The unit a column header gives its cells: "Penetration rate (min/m)",
   * "Bit diameter (mm)". A bare number in the cell is in that unit. The
   * column was read in the template's units whatever its header said, so 165
   * under "Bit diameter (mm)" was a 165 inch hole (a 2 m annulus and 1654
   * bags of cement in the bill of quantities) and 4 under "(min/m)" was
   * 4 m/min. */
  var RATE_HEADER_RE = new RegExp('(?:' + RATE_UNITS_SOURCE + ')(?![a-z])', 'i');
  var METRIC_HEADER_RE = /\b(millimet(?:re|er)s?|mms?|centimet(?:re|er)s?|cms?)\b/i;

  /* A whole number and a fraction of an inch with no unit ("6 1/2"), which
   * is how a bit is quoted. Groups are number, numerator, denominator. */
  var MIXED_NUMBER_RE = /(\d+(?:[.,]\d+)?)\s+(\d+)\s*\/\s*(\d+)/g;

  /* "8½" and "8-1/2" are how a bit size is stamped and typed; both used
   * to be read as 8 inches. The fraction is written out and the hyphen
   * dropped, so they reach the patterns above as "8 1/2". */
  var VULGAR_FRACTIONS = { '½': '1/2', '¼': '1/4', '¾': '3/4',
    '⅛': '1/8', '⅜': '3/8', '⅝': '5/8', '⅞': '7/8' };
  var VULGAR_RE = /[½¼¾⅛⅜⅝⅞]/g;
  var HYPHENATED_FRACTION_RE = /(\d)\s*-\s*(?=\d+\s*\/\s*\d)/g;

  /* No water well is drilled wider than this, in inches: a larger reading is
   * a bit size in millimetres with its unit left off. */
  var MAX_BIT_DIAMETER_IN = 36.0;

  /* Python guards both unit patterns with a lookbehind, (?<![\d./,]), which
   * keeps the denominator of "6 1/2" from being read as a number in its own
   * right. Lookbehind reached Safari only in 2023 and this page runs on
   * whatever handset a field office has, so the guard is applied by hand: a
   * match preceded by one of those characters is rejected and the search
   * resumes one character further on, which is what the Python engine does
   * when the lookbehind fails. */
  var UNIT_PREFIX_RE = /[\d./,]/;

  function searchUnit(re, text) {
    var match;
    re.lastIndex = 0;
    while ((match = re.exec(text)) !== null) {
      var before = match.index > 0 ? text.charAt(match.index - 1) : '';
      if (!UNIT_PREFIX_RE.test(before)) return match;
      re.lastIndex = match.index + 1;
    }
    return null;
  }

  /* Read the strike depths a cell names, in metres: [depths, reason], the
   * depths the cell can be read to name, or an empty list and the reason it
   * cannot be read confidently, which the caller raises as a flag. Recording
   * nothing and saying so is the right answer here, because a strike depth
   * places the screens.
   *
   * A strike cell used to be read as the last number after the last colon, so
   * "Water strike: 8 m at 14:30" recorded a 30 m strike - the minutes of the
   * clock time - "at 12 m and 30 m" recorded only 12 m, and a 0 typed in the
   * strike column to mean "no water on this row" recorded a strike at the
   * surface, which then seeded a 0-5 m screen against the topsoil (ROADMAP
   * data-ingestion-9). Clock times are removed before any number is read, a
   * number that carries a metre unit is a depth, and a zero is an empty
   * cell. */
  /* Two numbers with a slash between them: a fraction, a date, or a run
   * number, none of which is a depth. */
  var FRACTION_RE = /\d\s*\/\s*\d/;

  /** A depth in feet is converted, whether the cell says so ("at 90 ft") or
   * `unit` is 'ft', the unit its column or its sheet gives a bare number.
   * With `unit` null a bare number is refused, for the reason `refusal`
   * gives.
   * @param {*} value a cell
   * @param {string|null} [unit] the unit of a bare number: 'm' (the default) or 'ft'
   * @param {string} [refusal] why a bare number is refused when `unit` is null
   * @returns {[number[], string]}
   */
  function parseWaterStrikeDepths(value, unit, refusal) {
    var read = strikeDepths(value, unit === undefined ? 'm' : unit, refusal || '');
    return [read[0], read[1]];
  }

  /* parseWaterStrikeDepths, and beside each depth the number of feet it was
   * converted from, or null for a depth in metres: [depths, reason, feet]. */
  function strikeDepths(value, unit, refusal) {
    if (value === null || value === undefined) return [[], '', []];
    if (value instanceof Date) {
      /* A cell typed as a time comes back as a Date, and reading it as a
       * number recorded the year as a strike depth. */
      return [[], 'the cell holds a date or a time rather than a depth', []];
    }
    if (typeof value === 'boolean') return [[], '', []];
    if (typeof value === 'number') {
      if (!(value > 0)) return [[], '', []];
      if (unit === null) return [[], refusal, []];
      return [[inMetres(value, unit)], '', [unit === 'ft' ? value : null]];
    }

    /* A water level and a clock time are taken out before any number is
     * read, and counted: a cell whose only numbers were those names no
     * strike, and says so rather than recording nothing in silence. */
    var levels = 0, clocks = 0;
    var text = cleanText(value).replace(WATER_LEVEL_RE, function () {
      levels += 1;
      return ' ';
    }).replace(CLOCK_TIME_RE, function () {
      clocks += 1;
      return ' ';
    });
    /* A fraction between two digits is half a metre, or a date, or a run
     * number; it is not two depths and it is not its own denominator.
     * "Water strike 1/2 m" read as a strike at 2 m, which would place a
     * screen. Refusing it and saying so is the only honest answer. */
    if (FRACTION_RE.test(text)) {
      return [[], 'it writes a fraction or a date, which names no single depth', []];
    }
    /* Depths in metres and in feet, in the order the cell writes them. */
    var found = [], match, tokens, i, depth;
    [[DEPTH_LIST_RE, false], [FEET_LIST_RE, true]].forEach(function (pair) {
      var re = /** @type {RegExp} */ (pair[0]), feet = pair[1];
      re.lastIndex = 0;
      while ((match = re.exec(text)) !== null) {
        tokens = match[0].match(NUMBER_TOKEN_RE) || [];
        for (i = 0; i < tokens.length; i++) {
          depth = parseNumber(tokens[i]);
          if (depth !== null && depth > 0) {
            found.push([match.index, inMetres(depth, feet ? 'ft' : 'm'), feet ? depth : null]);
          }
        }
      }
    });
    if (found.length) {
      found.sort(function (a, b) { return a[0] - b[0]; });
      return [found.map(function (f) { return f[1]; }), '',
        found.map(function (f) { return f[2]; })];
    }

    /* No number carries a unit. A single number is the depth the note is
     * about ("First water strike: 12"); several are a sentence this parser
     * cannot take apart, and guessing one of them is worse than refusing. */
    var numbers = text.match(NUMBER_TOKEN_RE) || [];
    if (!numbers.length) {
      var named = [];
      if (levels) named.push('a water level');
      if (clocks) named.push('a clock time');
      if (named.length) {
        return [[], 'it names ' + named.join(' and ') + ' but no strike depth', []];
      }
      return [[], '', []];
    }
    if (numbers.length > 1) {
      return [[], 'it names several numbers and none of them carries a unit', []];
    }
    depth = parseNumber(numbers[0]);
    if (depth === null || depth <= 0) return [[], '', []];
    if (unit === null) return [[], refusal, []];
    return [[inMetres(depth, unit)], '', [unit === 'ft' ? depth : null]];
  }

  /* The flag raised for a strike cell that cannot be read as a depth.
   * Refusing the cell costs the log a strike, so the flag names the cell it
   * refused, why it refused it, and the wording that would have read. */
  function unreadableStrikeFlag(text, reason) {
    return { level: 'warning', code: 'water_strike_unreadable',
      message: 'Water strike cell "' + text + '" was not read as a depth: ' +
        reason + '. No strike was recorded from it; write each depth with ' +
        'its unit, as "water strike at 12 m and 30 m".' };
  }

  function fractionsWrittenOut(text) {
    return text.replace(VULGAR_RE, function (c) { return ' ' + VULGAR_FRACTIONS[c]; })
      .replace(HYPHENATED_FRACTION_RE, '$1 ');
  }

  /* A diameter in `unit` (the cell's or the header's) in inches. */
  function inches(number, unit) {
    if (number === null || number === undefined || !unit) return number;
    var u = String(unit).toLowerCase();
    if (u.indexOf('mm') === 0 || u.indexOf('millim') === 0) return pyRound(number / 25.4, 2);
    if (u.indexOf('cm') === 0 || u.indexOf('centim') === 0) return pyRound(number / 2.54, 2);
    return number;
  }

  /* The metric unit a diameter column header names, or null for inches. */
  function headerDiameterUnit(header) {
    var match = METRIC_HEADER_RE.exec(cleanText(header));
    return match ? match[1].toLowerCase() : null;
  }

  /* The penetration rate unit a column header names, if it names one. */
  function headerRateUnit(header) {
    var match = RATE_HEADER_RE.exec(cleanText(header));
    return match ? match[0] : null;
  }

  /** The drilled diameter in inches, converting the unit the cell carries.
   *
   * Crews quote a bit in millimetres as often as in inches, and the column
   * was read as a bare number, so "165 mm" was recorded as a 165 inch hole
   * (ROADMAP data-ingestion-15) - a metre and a half of annulus in the bill
   * of quantities and in the completion drawing. A cell with no unit is in
   * `unit`, the unit its column header names; with none, inches, which is the
   * unit the template column asks for ("Drilling diameter (in)") and the unit
   * the design rules are written in.
   *
   * A converted diameter is kept to two decimals: 165 mm is the metric name
   * of a 6.5 in bit, and 6.5 in is what the completion log should print.
   * @param {*} value a cell
   * @param {string|null} [unit] the unit the column header names
   * @returns {number|null}
   */
  function parseBitDiameterIn(value, unit) {
    if (value === null || value === undefined) return null;
    if (typeof value === 'boolean') return null;
    if (typeof value === 'number') return inches(value, unit);
    var text = fractionsWrittenOut(cleanText(value));
    var match = searchUnit(DIAMETER_UNIT_RE, text);
    if (match === null) {
      var mixed = searchUnit(MIXED_NUMBER_RE, text);
      if (mixed === null) return inches(parseNumber(text), unit);
      var whole = parseNumber(mixed[1]);
      if (whole !== null && Number(mixed[3]) !== 0) whole += Number(mixed[2]) / Number(mixed[3]);
      return inches(whole, unit);
    }
    var number = parseNumber(match[1]);
    if (number === null) return null;
    if (match[2] && Number(match[3]) !== 0) {
      /* "6 1/2 in" is six and a half inches, which is how a bit is quoted. */
      number += Number(match[2]) / Number(match[3]);
    }
    return inches(number, match[4]);
  }

  /* A penetration rate in `unit` (the cell's or the header's) in m/min. */
  function rateInMPerMin(number, unit) {
    if (number === null || number === undefined || !unit) return number;
    var u = String(unit).replace(/\s+/g, '').toLowerCase().replace(/per/g, '/');
    /* the length the rate is per, or per unit of time of: a foot is 0.3048 m */
    var length = RATE_FEET_RE.test(u) ? FOOT_M : 1.0;
    if (u.indexOf('min') === 0) {
      /* minutes per metre (or foot): the reciprocal, and a zero is not a
       * rate at all */
      return number > 0 ? length / number : null;
    }
    if (u.indexOf('s') === 0) {            /* seconds per metre (or foot) */
      return number > 0 ? 60.0 * length / number : null;
    }
    if (u.indexOf('/h') >= 0) return number * length / 60.0;
    return length !== 1.0 ? number * length : number;
  }

  /** The penetration rate in metres per minute, whichever way up it is
   * written.
   *
   * A driller times a rod with a stopwatch and writes what the watch says, so
   * the cell carries "5 min/m" as readily as "0.2 m/min" and a rig sheet
   * quotes metres per hour. The column was read as a bare number, so a hole
   * advancing at five minutes to the metre was recorded as five metres a
   * minute (ROADMAP data-ingestion-15), twenty-five times too fast. A cell
   * with no unit is in `unit`, the unit its column header names; with none,
   * metres per minute, which is the unit the template column asks for
   * ("Penetration rate (m/min)").
   * @param {*} value a cell
   * @param {string|null} [unit] the unit the column header names
   * @returns {number|null}
   */
  function parsePenetrationRateMPerMin(value, unit) {
    if (value === null || value === undefined) return null;
    if (typeof value === 'boolean') return null;
    if (typeof value === 'number') return rateInMPerMin(value, unit);
    var text = cleanText(value);
    var match = searchUnit(RATE_UNIT_RE, text);
    if (match === null) return rateInMPerMin(parseNumber(text), unit);
    var number = parseNumber(match[1]);
    if (number === null) return null;
    return rateInMPerMin(number, match[2]);
  }

  /** "25-35; 48-53 m" -> [[25, 35], [48, 53]]: the as-built screens a crew
   * writes on the sheet, as ranges separated by anything. A cell with no
   * range in it records no screens. The dashes are normalised first so a
   * range typed with an en or em dash is read as the range it is rather than
   * dropped (ROADMAP data-ingestion-8).
   * @param {*} value a cell
   * @returns {number[][]}
   */
  function parseInstalledScreens(value) {
    var text = normaliseDashes(cleanText(value)), out = [], match;
    var re = new RegExp(SCREEN_RANGE_SOURCE, 'g');
    while ((match = re.exec(text)) !== null) {
      var top = Number(match[1]), bottom = Number(match[2]);
      if (bottom < top) { var swap = top; top = bottom; bottom = swap; }
      if (bottom > top) out.push([top, bottom]);
    }
    return out.sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; });
  }

  /* The unit a bare depth is read in where nothing nearer names one: every
   * depth and rate unit the sheet names agreeing on feet makes it a sheet in
   * feet; naming none, or only metres, it is in metres, the unit the
   * template asks for; naming both, there is no unit to read a bare depth
   * in, and it is refused. */
  function sheetUnit(statements) {
    if (statements.length === 1 && statements[0] === 'ft') return 'ft';
    if (statements.indexOf('ft') >= 0) return null;
    return 'm';
  }

  function statementOf(unit) {
    if (unit === 'both') return ['ft', 'm'];
    return unit ? [unit] : [];
  }

  /* The length a rate unit is per, as a statement about the sheet. */
  function rateLength(unit) {
    if (!unit) return [];
    return RATE_FEET_RE.test(unit) ? ['ft'] : ['m'];
  }

  var DEPTH_FIELDS = ['borehole_depth_m', 'grouting_depth_m', 'installed_screens'];

  /**
   * @param {Grid} grid
   * @param {string} [source]
   * @returns {DrillingLog}
   */
  function drillingFromGrid(grid, source) {
    /** @type {Record<string, Array<*>>} */
    var rawFields = {};
    var fields = extractHeaderFields(grid, grid.length, rawFields);
    var site = siteFromFields(fields, source);
    var flags = [], intervals = [], strikes = [], zeroStrikeRows = 0, tooWide = [];
    var whyText = phraseTable('drilling.ambiguous_why');
    var located = findLogHeader(grid);

    /* What the sheet names its depths in, before any depth is read: a bare
     * number is read in the unit the sheet gives, and a sheet in feet that
     * gives its unit only in the total depth or the strike column still
     * gives it for every depth on the sheet. A drilling log was read in
     * metres whatever it said, so "Depth interval (ft)", "0-20 ft" and
     * "Total depth: 150 ft" made a 45.7 m hole a 150 m one, with no flag. */
    var statements = [];
    function state(units) {
      units.forEach(function (u) { if (statements.indexOf(u) < 0) statements.push(u); });
    }
    DEPTH_FIELDS.forEach(function (key) {
      if (!own(rawFields, key)) return;
      state(statementOf(headerLengthUnit(rawFields[key][0])));
      state(lengthUnits(rawFields[key][1])[1]);
    });
    /** @type {Record<string, string|null>} */
    var headerUnits = { interval: null, strike: null };
    var rateUnit = null, diameterUnit = null;
    /** @type {Record<string, number>} */
    var cols = {};
    var r, row;
    if (located) {
      cols = located.cols;
      var headerCell = function (key) {
        var c = cols[key], headerRow = grid[/** @type {Rec} */ (located).row] || [];
        return (c !== undefined && c < headerRow.length) ? headerRow[c] : null;
      };
      /* the unit the column header names is the unit of a bare number */
      rateUnit = headerRateUnit(headerCell('rate'));
      diameterUnit = headerDiameterUnit(headerCell('diameter'));
      headerUnits = { interval: headerLengthUnit(headerCell('interval')),
        strike: headerLengthUnit(headerCell('strike')) };
      state(statementOf(headerUnits.interval));
      state(statementOf(headerUnits.strike));
      state(rateLength(rateUnit));
      for (r = located.row + 1; r < grid.length; r++) {
        row = grid[r] || [];
        ['interval', 'strike'].forEach(function (key) {
          var c = cols[key];
          if (c !== undefined && c < row.length) state(lengthUnits(cleanText(row[c]))[1]);
        });
        var rc = cols.rate;
        if (rc !== undefined && rc < row.length && typeof row[rc] === 'string') {
          var rateMatch = searchUnit(RATE_UNIT_RE, cleanText(row[rc]));
          state(rateLength(rateMatch ? rateMatch[2] : null));
        }
      }
    }
    grid.forEach(function (gridRow) {
      (gridRow || []).forEach(function (c) {
        var text = cleanText(c);
        if (text.toLowerCase().indexOf('water strike') >= 0 &&
            text.toLowerCase().indexOf('note') !== 0) {
          state(lengthUnits(text)[1]);
        }
      });
    });
    var sheet = sheetUnit(statements);

    var feet = { depths: 0, deepest: 0.0, bySheet: false, rates: 0 };
    /* `value` in metres, counting a conversion from feet */
    function counted(value, unit, cellUnits, column) {
      if (unit === 'ft') {
        feet.depths += 1;
        feet.deepest = Math.max(feet.deepest, value);
        if (!cellUnits.length && column !== 'ft' && column !== 'm') feet.bySheet = true;
      }
      return inMetres(value, unit);
    }

    if (located) {
      for (r = located.row + 1; r < grid.length; r++) {
        row = grid[r] || [];
        var cell = function (key) {
          var c = cols[key];
          return (c !== undefined && c < row.length) ? row[c] : null;
        };
        var rawInterval = cell('interval');
        if (cleanText(rawInterval).toLowerCase().indexOf('note') === 0) continue;
        if (rawInterval instanceof Date) {
          /* Excel turns "5-10" typed into a General cell into 10 May. Losing
           * the row is better than a 5 to 2026 m interval, but the crew has to
           * know a row went missing. */
          flags.push({
            level: 'warning', code: 'interval_read_as_date',
            message: 'Depth interval cell holds the date ' +
              formatDayMonYear(rawInterval) + ' - Excel converts entries like ' +
              '"5-10" into dates. Format the depth column as Text and retype ' +
              'the interval; this row was skipped.',
          });
          continue;
        }
        /* Word turns "5-10" into "5–10" as the crew types the sheet and the
         * en dash survives the copy into Excel, but the interval pattern
         * lists only the plain hyphen, so the row was dropped without a word
         * and the gap it left was reported as a gap in the crew's own log
         * (ROADMAP data-ingestion-8). Normalising the dashes reads the
         * interval as it was written, whichever dash was typed. A unit
         * against each depth ("30 m - 40 m", "5m-10m", "0-20 ft") is dropped
         * first for the same reason: the row used to be skipped with its
         * description and its strike. It is kept to read the depths in. */
        var split = lengthUnits(rawInterval);
        var cellUnits = split[1];
        var interval = parseDepthInterval(split[0]);
        if (!interval) {
          if (readsAsInterval(rawInterval)) {
            flags.push({
              level: 'warning', code: 'interval_unreadable',
              message: phrase('drilling.interval_unreadable', { value: cleanText(rawInterval) }),
            });
          }
          continue;
        }
        var resolved = resolveUnit(cellUnits, headerUnits.interval, sheet);
        if (resolved[0] === null) {
          flags.push({
            level: 'warning', code: 'depth_unit_ambiguous',
            message: phrase('drilling.row_unit_ambiguous',
              { value: cleanText(rawInterval), why: whyText[resolved[1]] }),
          });
          continue;
        }
        var top = counted(interval[0], resolved[0], cellUnits, headerUnits.interval);
        var bottom = counted(interval[1], resolved[0], cellUnits, headerUnits.interval);
        var diameter = parseBitDiameterIn(cell('diameter'), diameterUnit);
        if (diameter !== null && diameter > MAX_BIT_DIAMETER_IN) {
          /* a bit size in millimetres with its unit left off: sized as inches
           * it made a two-metre annulus and a thousand bags of cement */
          tooWide.push(cleanText(cell('diameter')));
          diameter = null;
        }
        var rawRate = cell('rate');
        var rate = parsePenetrationRateMPerMin(rawRate, rateUnit);
        var rateSaid = typeof rawRate === 'string'
          ? searchUnit(RATE_UNIT_RE, cleanText(rawRate)) : null;
        var said = rateSaid ? rateSaid[2] : rateUnit;
        if (rate !== null && rate !== undefined && rateLength(said)[0] === 'ft') feet.rates += 1;
        intervals.push({
          top_m: top, bottom_m: bottom,
          description: cleanText(cell('description')),
          from_time: cleanText(cell('from_time')),
          to_time: cleanText(cell('to_time')),
          penetration_rate_m_per_min: rate,
          bit_diameter_in: diameter,
        });
        var rawStrike = cell('strike');
        var strikeCellUnits = typeof rawStrike === 'string'
          ? lengthUnits(cleanText(rawStrike))[1] : [];
        var strikeUnit = resolveUnit([], headerUnits.strike, sheet);
        var readStrike = strikeDepths(rawStrike, strikeUnit[0],
          strikeUnit[1] ? 'it ' + whyText[strikeUnit[1]] : '');
        var converted = readStrike[2].filter(function (f) { return f !== null; });
        if (converted.length) {
          feet.depths += converted.length;
          feet.deepest = Math.max.apply(null, [feet.deepest].concat(converted));
          if (!strikeCellUnits.length && headerUnits.strike !== 'ft' &&
              headerUnits.strike !== 'm') feet.bySheet = true;
        }
        readStrike[0].forEach(function (depth) { strikes.push(depth); });
        if (readStrike[1]) {
          flags.push(unreadableStrikeFlag(cleanText(rawStrike), readStrike[1]));
        } else if (!readStrike[0].length && parseNumber(rawStrike) === 0) {
          /* A crew fills the strike column with 0 to mean "no water on this
           * row". Read as a number it was a strike at 0 m, which seeded a
           * screen against the topsoil (ROADMAP data-ingestion-9); it is
           * counted here so the refusal is visible rather than silent. */
          zeroStrikeRows += 1;
        }
      }

      if (zeroStrikeRows) {
        flags.push({ level: 'info', code: 'water_strike_zero_ignored',
          message: 'The water strike column holds 0 on ' + zeroStrikeRows +
            ' row(s); a zero there is read as no strike on that row, not as ' +
            'a strike at 0 m.' });
      }
      if (tooWide.length) {
        var wideValues = tooWide.filter(function (v, i) { return tooWide.indexOf(v) === i; });
        flags.push({ level: 'warning', code: 'diameter_implausible',
          message: 'Drilled diameter ' + wideValues.join(', ') + ' reads as more than ' +
            formatG(MAX_BIT_DIAMETER_IN) + ' inches, wider than any water well bit, so ' +
            'it was not recorded; write the unit in the cell or the column header, ' +
            'as "165 mm".' });
      }
    }

    /* Water strikes noted as text lines ("First water strike: 12m"). The note
     * used to be read as the last number after the last colon, so
     * "Water strike: 8 m at 14:30" recorded a 30 m strike and a note naming
     * two strikes recorded only the first (ROADMAP data-ingestion-9). A bare
     * number in a note is in the sheet's unit, and "at 90 ft" is in feet. */
    var noteUnit = resolveUnit([], null, sheet);
    grid.forEach(function (gridRow) {
      (gridRow || []).forEach(function (c) {
        var raw = cleanText(c);
        var text = raw.toLowerCase();
        if (text.indexOf('water strike') >= 0 && text.indexOf('note') !== 0) {
          var read = strikeDepths(raw, noteUnit[0],
            noteUnit[1] ? 'it ' + whyText[noteUnit[1]] : '');
          read[0].forEach(function (value, i) {
            if (strikes.indexOf(value) >= 0) return;
            strikes.push(value);
            if (read[2][i] !== null) {
              feet.depths += 1;
              feet.deepest = Math.max(feet.deepest, read[2][i]);
              if (!lengthUnits(raw)[1].length) feet.bySheet = true;
            }
          });
          if (read[1]) {
            /* A cell in the strike column that is also a note has already
             * been refused once by the loop above, and one refusal of one
             * cell is one flag. */
            var flag = unreadableStrikeFlag(raw, read[1]);
            var told = flags.some(function (f) { return f.message === flag.message; });
            if (!told) flags.push(flag);
          }
        }
      });
    });

    /* The depths the header block gives, each read in its label's unit or
     * the one the cell writes beside it. */
    var fieldNames = phraseTable('drilling.field_names');
    DEPTH_FIELDS.forEach(function (key) {
      if (!own(rawFields, key)) return;
      var label = rawFields[key][0], value = rawFields[key][1];
      var parts = lengthUnits(value);
      var column = headerLengthUnit(label);
      var unit = resolveUnit(parts[1], column, sheet);
      if (unit[0] === null) {
        delete fields[key];
        flags.push({ level: 'warning', code: 'depth_unit_ambiguous',
          message: phrase('drilling.value_unit_ambiguous', { what: fieldNames[key],
            value: cleanText(value), why: whyText[unit[1]] }) });
      } else if (key === 'installed_screens') {
        fields[key] = parseInstalledScreens(parts[0]).map(function (range) {
          return [counted(range[0], unit[0], parts[1], column),
            counted(range[1], unit[0], parts[1], column)];
        });
      } else if (unit[0] === 'ft') {
        fields[key] = counted(Number(fields[key]), unit[0], parts[1], column);
      }
    });
    var screens = Array.isArray(fields.installed_screens) ? fields.installed_screens
      : parseInstalledScreens(fields.installed_screens || '');

    var stated = fields.borehole_depth_m === undefined ? null : fields.borehole_depth_m;
    var total = stated;
    if ((total === null || total === undefined) && intervals.length) {
      total = arrMax(intervals.map(function (iv) { return iv.bottom_m; }));
    }

    intervals.sort(function (a, b) { return a.top_m - b.top_m; });
    strikes.sort(function (a, b) { return a - b; });

    /* A strike below the bottom of the hole is a number the drilling never
     * reached. It survives only as a figure printed to the client - the
     * handover report lists the strikes - because the screen designer clips
     * it out, so nothing else in the toolkit ever contradicts it. */
    if (total !== null && total !== undefined) {
      var tooDeep = strikes.filter(function (v) { return v > Number(total); });
      if (tooDeep.length) {
        strikes = strikes.filter(function (v) { return v <= Number(total); });
        flags.push({
          level: 'warning',
          code: 'water_strike_below_total_depth',
          message: 'Water ' + plural(tooDeep.length, 'strike') + ' at ' +
            tooDeep.map(function (v) { return formatG(v) + ' m'; }).join(', ') +
            ' below the recorded total depth of ' + formatG(Number(total)) +
            ' m, so it was not recorded; check the cell it came from.',
        });
      }
    }

    if (feet.depths || feet.rates) {
      var told = [];
      if (feet.depths) {
        told.push(phrase('drilling.feet_converted', { n: feet.depths, feet: feet.deepest,
          metres: inMetres(feet.deepest, 'ft') }));
        if (feet.bySheet) told.push(phrase('drilling.feet_by_sheet'));
      }
      if (feet.rates) told.push(phrase('drilling.feet_rates', { n: feet.rates }));
      flags.push({ level: 'info', code: 'feet_converted', message: told.join(' ') });
    }

    /** @type {DrillingLog} */
    var log = {
      site: site, borehole_ref: String(fields.borehole_ref || ''),
      total_depth_m: total === undefined ? null : total,
      drilling_method: fields.drilling_method || '',
      intervals: intervals, water_strikes_m: strikes,
      grouting_depth_m: fields.grouting_depth_m === undefined ? null : fields.grouting_depth_m,
      /* the screens the crew actually set, when the sheet records them:
       * with these the drawing is an as-built record, without them it is a
       * design generated by the rules, and says so */
      installed_screens_m: screens,
      start_date: String(fields.start_date || ''),
      completion_date: String(fields.completion_date || ''),
      status: fields.status || '', source: String(source || ''), flags: [],
    };

    /* Consistency of the interval column, against the deepest bottom logged
     * so far rather than the row before: a clay lens logged inside a longer
     * interval (0-30, 5-10, 30-45) is not a gap from 10 m to 30 m, which the
     * 0-30 m row covers. */
    /** @type {number|null} */
    var deepest = null;
    for (var k = 0; k < intervals.length; k++) {
      var b = intervals[k];
      if (deepest !== null && b.top_m < deepest - 1e-9) {
        flags.push({ level: 'warning', code: 'interval_overlap',
          message: phrase('drilling.interval_overlap', { depth: b.top_m }) });
      } else if (deepest !== null && b.top_m > deepest + 1e-9) {
        flags.push({ level: 'warning', code: 'interval_gap',
          message: phrase('drilling.interval_gap', { top: deepest, bottom: b.top_m }) });
      }
      deepest = deepest === null ? b.bottom_m : Math.max(deepest, b.bottom_m);
    }
    /* Only a total the sheet states can differ from the log; one worked out
     * from the intervals is their deepest bottom. The last row by top used
     * to be compared, so a nested fracture row at the foot of the table was
     * "the deepest logged interval", and a derived total was called
     * "stated". */
    if (stated && deepest !== null && Math.abs(deepest - stated) > 1e-6) {
      flags.push({ level: 'warning', code: 'depth_mismatch',
        message: phrase('drilling.depth_mismatch', { stated: stated, deepest: deepest }) });
    }
    if (!intervals.length) {
      flags.push({ level: 'error', code: 'no_intervals',
        message: 'No depth intervals found in the log.' });
    }
    var missingDesc = intervals.filter(function (iv) { return !iv.description; }).length;
    if (intervals.length && missingDesc) {
      flags.push({ level: 'info', code: 'missing_lithology',
        message: missingDesc + ' interval(s) have no lithology description.' });
    }
    log.flags = flags;
    return log;
  }

  var MONTH_ABBR = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug',
    'Sep', 'Oct', 'Nov', 'Dec'];
  function formatDayMonYear(d) {
    return String(d.getUTCDate()).padStart(2, '0') + ' ' +
      MONTH_ABBR[d.getUTCMonth()] + ' ' + d.getUTCFullYear();
  }

  /* --- water quality sheets ------------------------------------------------- */

  /* The results table's header row, its columns, and the unit it declares
   * (waterquality.py _find_results_header). A unit in the result column's
   * header ("Result (ug/L)") is the unit of every row whose own unit cell is
   * blank; it was dropped, so arsenic 5 under "Result (ug/L)" was read as 5
   * mg/L. Only a unit this engine can read is taken. A row the header's unit
   * cannot measure (E. coli under "Result (mg/L)") is then refused rather
   * than read in its guideline's unit; that is a choice (QUESTIONS.md item
   * 24). */
  function findResultsHeader(grid) {
    for (var r = 0; r < grid.length; r++) {
      var texts = rowText(grid[r]);
      var cols = {};
      for (var c = 0; c < texts.length; c++) {
        var t = texts[c];
        if (!t) continue;
        if (t.indexOf('parameter') === 0 || t.indexOf('determinand') === 0) cols.parameter = c;
        else if (t.indexOf('unit') === 0) cols.unit = c;
        else if (t.indexOf('value') === 0 || t.indexOf('result') === 0) cols.value = c;
        else if (t.indexOf('detection') >= 0 || t === 'dl') cols.dl = c;
        else if (t.indexOf('method') === 0) cols.method = c;
      }
      if ('parameter' in cols && 'value' in cols) {
        var declared = unitFromLabel(cleanText(grid[r][cols.value]), null);
        return { row: r, cols: cols, unit: declared.unit ? declared.written : '' };
      }
    }
    return null;
  }

  /* What a laboratory writes for "nothing found": a below-detection result
   * with no stated limit, judged by the assessment per parameter. The same
   * words often carry that limit after them ("ND (<0.05)", "BDL (0.02)",
   * "ND at 0.05"); only an exact match once counted, and every one of those
   * was graded as a measured concentration exceeding a health guideline. */
  var ABSENCE_TOKENS = ['absent', 'nd', 'n.d', 'n/d', 'nil', 'none', 'not detected',
    'none detected', 'bdl', 'below detection', 'below detection limit', '<dl',
    'negative', 'neg'];

  /* What a laboratory writes when it saw the determinand and put no number
   * to it. For a determinand whose limit is zero that is the whole finding:
   * a sample with E. coli 0 and total coliforms TNTC was graded "Safe"
   * because the count read as "not measured". */
  var PRESENCE_TOKENS = ['tntc', 't.n.t.c', 'too numerous to count', 'confluent',
    'confluent growth', 'present', 'positive', 'pos', '+ve', 'detected'];

  /* Words that introduce a lower bound, and whether the bound itself is a
   * possible value. ">=50" is at least 50; ">50" is more than 50. */
  /** @type {Array<[string, boolean]>} */
  var LOWER_BOUND_WORDS = [['>=', true], ['=>', true], ['>', false],
    ['at least', true], ['more than', false], ['greater than', false],
    ['above', false], ['over', false]];

  /* words that introduce an upper bound: "<0.05" is below a limit of 0.05 */
  var UPPER_BOUND_WORDS = ['<=', '=<', '<', 'less than'];

  /* What may stand between an absence word and the limit it carries:
   * "ND (DL 0.05)", "ND (DL=0.05)", "ND at 0.05", "ND (LOD 0.05)". */
  var LIMIT_WORD_RE = /^(?:at|dl|d\.l\.?|lod|loq|mdl|detection limit|limit of detection|limit)\s*[=:]?\s*/;

  /* a bound with no number: "<DL", "< LOQ" */
  var LIMIT_ONLY_RE = /^(?:dl|d\.l\.?|lod|loq|mdl|detection limit|detection)$/;

  /* "Absent/100 mL", "Present in 100 mL": the volume examined, not a limit */
  var VOLUME_RE = /^(?:\/|per|in)\s*100\s*ml$/;

  /* A number as a laboratory writes one: "50", "0,05", "1,250.5", "1.234,5",
   * "5.0E-02". The exponent is part of it: read as far as the "E", "5.0E-02
   * mg/L" was 5.0 followed by a unit nobody could read, so the unit was
   * dropped and arsenic at five times its guideline was read in the row's
   * ug/L and graded Safe. Groups of three are a thousands separator, as
   * parseNumber reads them, so "1,250.5 mg/L" is not 1,250 and ".5 mg/L"
   * (waterquality.py _NUMBER). */
  var QUALITY_NUMBER = '(?:\\d{1,3}(?:[.,]\\d{3})+(?:[.,]\\d+)?|\\d+(?:[.,]\\d+)?|[.,]\\d+)' +
    '(?:e[+-]?\\d+)?';
  /* a number and the unit written after it: "50", "50 mg/L", "0,05mg/l" */
  var NUMBER_AND_UNIT_RE = new RegExp('^(' + QUALITY_NUMBER +
    ')\\s*([^\\d\\s()[\\]][\\s\\S]*)?$');
  /* a measured value and whatever is written after it */
  var MEASURED_RE = new RegExp(QUALITY_NUMBER + '\\s*([\\s\\S]*)$');
  /* The families a laboratory's result is written in. A unit of another
   * family after a number is a laboratory's qualifier letter ("0.003 D",
   * "0.2 H": a day and an hour to the unit reader), and so is any single
   * letter ("0.1 C", "0.5 F"): read as units, they made the result
   * unreadable (waterquality.py _QUALITY_DIMENSIONS). */
  var QUALITY_DIMENSIONS = ['concentration', 'conductivity', 'turbidity', 'microbial',
    'ph', 'temperature'];
  /* the most words a unit is written in ("cfu per 100 ml" is four): the runs
   * of a cell's words tried as a unit (waterquality.py _UNIT_WORDS) */
  var UNIT_WORDS = 6;
  /* a reference temperature after a unit: "450 uS/cm at 25 C", "@ 20 oC" */
  var REFERENCE_TEMPERATURE_RE =
    /\s*(?:@|\bat)\s*\d+(?:[.,]\d+)?(?:\s*(?:°|º|o|deg\.?)?\s*[cf])?$/;
  /* a basis named after a number without "as": nitrogen ("10 N", "10
   * (NO3-N)", "10 mg N/L") or calcium carbonate ("25 (CaCO3)") */
  var CELL_BASIS_RE = new RegExp('\\bcaco3\\b' +
    '|\\b(?:(?:no3|no2|nh4|nh3)\\s*[-–—−]{0,2}\\s*)?(?:n|nitrogen)\\b');

  /* Whether the text is a unit a laboratory's result is written in. A unit
   * of another family is a laboratory's qualifier letter ("0.003 D", "0.2
   * H"), and so is a lone letter ("0.1 C", "0.5 F"), unless the row's own
   * unit is in the letter's family: "68 F" in a row of degrees Celsius is 20
   * deg C (waterquality.py _quality_unit). */
  function isQualityUnit(text, dimension) {
    var unit = parseUnit(text);
    if (!unit) return false;
    return unit.dimension === dimension || (QUALITY_DIMENSIONS.indexOf(unit.dimension) >= 0 &&
      text.replace(/\s+/g, '').length > 1);
  }

  /* whether the text is written as a unit: one a result is written in, one
   * refused by name ("ppt"), or a ratio this engine does not know ("meq/L")
   * (waterquality.py _unit_like) */
  function isUnitLike(text, dimension) {
    return isQualityUnit(text, dimension) || text.indexOf('/') >= 0 ||
      own(AMBIGUOUS_UNITS, normaliseUnit(text));
  }

  /* The unit written after a measured value: '' for none, null to refuse
   * (waterquality.py _measured_unit). A unit this engine reads is taken; a
   * note holding no unit leaves the reading as it was ("0.5 ND", "8
   * (field)", "0.003 D"); anything else refuses the cell: a unit with more
   * written beside it ("0.05 mg/L As", "25 mg/L CaCO3"), a basis written
   * without "as" ("10 NO3-N", "10 (N)"), a unit this engine does not read
   * ("5 meq/L") or a note that holds one ("0.05 (DL 0.01 mg/L)"). Refusing
   * "0.05 mg/L As" rather than reading its "mg/L" is a choice (QUESTIONS.md
   * item 24). */
  function measuredUnit(rest, dimension) {
    /** @type {string[]} */
    var notes = [];
    var text = rest.replace(/^\.+/, '').replace(/[([]([^()[\]]*)[)\]]/g,
      function (whole, inside) {
        /* a bracket that is a unit or states a basis is read; one that is
         * anything else is a note */
        var held = inside.trim();
        if (isQualityUnit(held, dimension) || /^as\s/.test(held) || CELL_BASIS_RE.test(held)) {
          return ' ' + held + ' ';
        }
        notes.push(held);
        return ' ';
      });
    /* a stray bracket ("(0.05 mg/L)"), an asterisk and a comma are not part
     * of a unit */
    text = text.replace(/[()[\]*,;:]/g, ' ');
    text = text.trim().replace(REFERENCE_TEMPERATURE_RE, '').replace(/\s+/g, ' ').trim();
    if (text && isQualityUnit(text, dimension)) return text;
    var tokens = text ? text.split(' ') : [];
    if (tokens.indexOf('as') >= 0 || CELL_BASIS_RE.test(text)) return null;
    for (var i = 0; i < tokens.length; i++) {
      for (var j = i + 1; j <= Math.min(i + UNIT_WORDS, tokens.length); j++) {
        if (isUnitLike(tokens.slice(i, j).join(' '), dimension)) return null;
      }
    }
    var noted = notes.some(function (note) {
      return note.split(/\s+/).some(function (word) {
        return !!word && isUnitLike(word, dimension);
      });
    });
    return noted ? null : '';
  }

  /* Python's str.strip(chars): the set, from both ends. */
  function stripChars(text, chars) {
    var start = 0, end = text.length;
    while (start < end && chars.indexOf(text.charAt(start)) >= 0) start++;
    while (end > start && chars.indexOf(text.charAt(end - 1)) >= 0) end--;
    return text.slice(start, end);
  }

  /* Python's str.isalpha for one character, as far as a laboratory cell
   * needs it: a letter is a character that has a case. */
  function isLetter(ch) {
    return ch.toLowerCase() !== ch.toUpperCase();
  }

  /* The longest of `words` the text starts with, as a whole word. */
  function leadingWord(text, words) {
    var sorted = words.slice().sort(function (a, b) { return b.length - a.length; });
    for (var i = 0; i < sorted.length; i++) {
      var word = sorted[i];
      if (text.indexOf(word) === 0) {
        var rest = text.slice(word.length);
        if (!rest || !isLetter(rest.charAt(0))) return word;
      }
    }
    return null;
  }

  function numberAndUnit(text) {
    var m = NUMBER_AND_UNIT_RE.exec(stripChars(text.trim(), '()[]').trim());
    if (!m) return null;
    var unit = (m[2] || '').trim().replace(/\.+$/, '').trim();
    return [parseNumber(m[1]), unit];
  }

  /** What a laboratory's result cell says, in a row whose unit is of the
   * given dimension: waterquality.py _read_cell.
   *
   * kind is number, below (a non-detect, with the limit it states if any),
   * above (a lower bound: ">50", "TNTC"), empty, text (words that are not a
   * result, such as "Not analysed") or unreadable: a cell that starts like a
   * qualified result and could not be read. That last one used to fall
   * through to a plain number parse, which read "ND (DL 0.05)" as a measured
   * 0.05, ">50 mg/L" as exactly 50 and "Absent/100 mL" as a count of 100.
   * @param {*} rawValue a cell
   * @param {string=} dimension the dimension of the row's own unit, if it
   *   states one: a lone letter of that family is a unit ("68 F" in a row of
   *   degrees Celsius), and of another a laboratory's qualifier ("0.1 C")
   */
  function readQualityCell(rawValue, dimension) {
    function reading(kind, number, unit, inclusive) {
      return { kind: kind, number: number === undefined ? null : number,
        unit: unit || '', inclusive: !!inclusive };
    }
    if (typeof rawValue === 'number') {
      var n = parseNumber(rawValue);
      return reading(n === null ? 'empty' : 'number', n);
    }
    var text = cleanText(rawValue);
    if (!text) return reading('empty');
    var plain = text.toLowerCase().replace(/≥/g, '>=').replace(/≤/g, '<=')
      .replace(/\.+$/, '').trim();
    var unreadable = reading('unreadable');

    function below(rest) {
      /* what follows an absence word or a "<": nothing, the volume
       * examined, or a limit with an optional unit */
      rest = rest.trim().replace(/^[,;:.-]+/, '').trim();
      rest = stripChars(rest, '()[]').trim();
      if (!rest || VOLUME_RE.test(rest) || LIMIT_ONLY_RE.test(rest)) {
        return reading('below');
      }
      rest = rest.replace(LIMIT_WORD_RE, '');
      rest = rest.replace(/^(?:<=|=<|<)\s*/, '');
      var read = numberAndUnit(rest);
      return read ? reading('below', read[0], read[1]) : unreadable;
    }

    function above(rest, inclusive) {
      rest = stripChars(rest.trim(), '()[]').trim();
      var plus = /^(\d+(?:[.,]\d+)?|[.,]\d+)\s*\+\s*([\s\S]*)$/.exec(rest);
      if (plus) {
        rest = plus[1] + ' ' + plus[2];
        inclusive = true;
      }
      var read = numberAndUnit(rest);
      return read ? reading('above', read[0], read[1], inclusive) : unreadable;
    }

    var word = leadingWord(plain, ABSENCE_TOKENS);
    if (word !== null) return below(plain.slice(word.length));
    word = leadingWord(plain, PRESENCE_TOKENS);
    if (word !== null) {
      var rest = plain.slice(word.length).trim().replace(/^[,;:-]+/, '').trim();
      if (!rest || VOLUME_RE.test(rest)) return reading('above', 0, '', false);
      /* "TNTC (>300)": the count is at least the stated bound */
      var inner = stripChars(rest, '()[]').trim();
      for (var i = 0; i < LOWER_BOUND_WORDS.length; i++) {
        if (inner.indexOf(LOWER_BOUND_WORDS[i][0]) === 0) {
          return above(inner.slice(LOWER_BOUND_WORDS[i][0].length),
            LOWER_BOUND_WORDS[i][1]);
        }
      }
      return unreadable;
    }
    for (var u = 0; u < UPPER_BOUND_WORDS.length; u++) {
      if (plain.indexOf(UPPER_BOUND_WORDS[u]) === 0) {
        return below(plain.slice(UPPER_BOUND_WORDS[u].length));
      }
    }
    for (var l = 0; l < LOWER_BOUND_WORDS.length; l++) {
      if (plain.indexOf(LOWER_BOUND_WORDS[l][0]) === 0) {
        return above(plain.slice(LOWER_BOUND_WORDS[l][0].length),
          LOWER_BOUND_WORDS[l][1]);
      }
    }
    /* "50+" is 50 or more */
    if (/^(\d+(?:[.,]\d+)?|[.,]\d+)\s*\+/.test(plain)) return above(plain, true);
    var number = parseNumber(rawValue);
    if (number === null) return reading('text');
    /* A unit written after a measured value is read as it is after a bound:
     * "0.05 mg/L" in a ug/L row was read as 0.05 ug/L. A note beside the
     * number ("0.5 ND", "8 (field)", "8*") leaves the reading as it was, and a
     * unit that cannot be read as written refuses the cell (measuredUnit). */
    var unit = '';
    var written = MEASURED_RE.exec(plain);
    if (written) {
      unit = measuredUnit(written[1], dimension);
      if (unit === null) return unreadable;
    }
    return reading('number', number, unit);
  }

  /* a unit read from the lower-cased cell, in the case the cell wrote it */
  function unitAsWritten(text, unit) {
    var at = unit ? text.toLowerCase().lastIndexOf(unit) : -1;
    return at >= 0 ? text.slice(at, at + unit.length) : unit;
  }

  /* The number on the row's scale, and the unit to record for the row. A
   * unit written in the cell ("ND (<0.05 mg/L)") is read, not dropped: it
   * becomes the row's unit when the unit column is blank, and is converted
   * onto the column's unit when the two differ. [null, rowUnit] when they
   * cannot be reconciled, which is never the same as zero. A chemical basis
   * stated on one side only is not a contradiction (unitsComparable): "46
   * mg/L" in a column of "mg/L as CaCO3" is the column's scale, and "10 mg/L
   * as N" in a column of "mg/L" keeps the basis the cell names. */
  function inRowUnit(number, cellUnit, rowUnit) {
    if (!cellUnit) return [number, rowUnit];
    if (!normaliseUnit(rowUnit)) return [number, cellUnit];
    if (normaliseUnit(cellUnit) === normaliseUnit(rowUnit)) return [number, rowUnit];
    var source = parseUnit(cellUnit), target = parseUnit(rowUnit);
    if (!source || !target || source.dimension !== target.dimension ||
        (source.basis && target.basis && source.basis !== target.basis)) {
      return [null, rowUnit];
    }
    if (source.basis && !target.basis) return [number, cellUnit];
    return [convertUnit(number, cellUnit, rowUnit), rowUnit];
  }

  /**
   * @param {Grid} grid
   * @param {string} [source]
   * @returns {QualitySample}
   */
  function qualityFromGrid(grid, source) {
    var fields = extractHeaderFields(grid);
    var site = siteFromFields(fields, source);
    var flags = [];
    var located = findResultsHeader(grid);
    if (!located) {
      throw new Error('No results table (Parameter/Value) found in ' + (source || 'the sheet'));
    }
    var cols = located.cols, results = [];

    for (var r = located.row + 1; r < grid.length; r++) {
      var row = grid[r] || [];
      var cell = function (key) {
        var c = cols[key];
        return (c !== undefined && c < row.length) ? row[c] : null;
      };
      var parameter = cleanText(cell('parameter'));
      if (!parameter || parameter.toLowerCase().indexOf('note') === 0) continue;
      var rawValue = cell('value');
      var unit = cleanText(cell('unit'));
      if (located.unit && !normaliseUnit(unit)) unit = located.unit;
      var dl = parseNumber(cell('dl'));
      var declared = parseUnit(unit);
      var read = readQualityCell(rawValue, declared ? declared.dimension : undefined);
      var kind = read.kind, number = read.number;
      if (number !== null) {
        var onScale = inRowUnit(number, unitAsWritten(cleanText(rawValue), read.unit),
          unit);
        number = onScale[0];
        unit = onScale[1];
        /* the cell names a unit the column contradicts */
        if (number === null) kind = 'unreadable';
      }
      var value = null, greaterThan = null, belowDetection = false;
      if (kind === 'number') {
        value = number;
      } else if (kind === 'below') {
        /* "<X" bounds the true concentration above by X, and so does a
         * filled detection-limit column; the larger of the two is the one
         * the laboratory can stand behind. Taking the column alone graded
         * "<0.05" beside a column of 0.001 against 0.001. */
        belowDetection = true;
        var stated = [number, dl].filter(function (x) { return x !== null; });
        dl = stated.length ? Math.max.apply(null, stated) : null;
      } else if (kind === 'above') {
        greaterThan = number;
      } else if (kind === 'empty') {
        /* A blank result beside a filled detection-limit column is the one
         * layout where the column is the result. Not analysed, N/A, TNTC,
         * Present and ">50" are not blanks, and reading any of them this way
         * reported a detection as "not detected". */
        belowDetection = dl !== null;
      }
      results.push({
        parameter: parameter, value: value, unit: unit,
        detection_limit: dl,
        below_detection: belowDetection,
        method: cleanText(cell('method')),
        greater_than: greaterThan,
        greater_than_inclusive: read.inclusive,
        unreadable: kind === 'unreadable' ? cleanText(rawValue) : '',
      });
    }

    /** @type {QualitySample} */
    var sample = {
      site: site, sample_id: String(fields.sample_id || ''),
      borehole_ref: String(fields.borehole_ref || ''),
      sample_date: String(fields.sample_date !== undefined ? fields.sample_date
        : (fields.date || '')),
      laboratory: fields.laboratory || '', results: results,
      source: String(source || ''), flags: [],
    };
    var measured = results.filter(function (r2) {
      return r2.value !== null || r2.below_detection;
    });
    if (!measured.length) {
      flags.push({ level: 'error', code: 'no_results',
        message: 'No measured values found in the sheet.' });
    }
    sample.flags = flags;
    return sample;
  }

  /* --- pumping test sheets --------------------------------------------------
   * The paper layout records readings in side-by-side hourly column groups,
   * each with Time (min), Water Level (m) and Drawdown (m), followed by a
   * Recovery block. The recorded drawdown column is the increment between
   * successive readings, not drawdown below static, so only time and water
   * level are read and true drawdown is always recomputed.
   */

  /* Units are read, not assumed. The sheet's own headings say what the numbers
   * mean - "Time (min)", "Discharge per step (m3/h)" - and a crew that heads
   * the column L/s or records the times in hours means exactly that. A unit
   * this engine cannot read is refused rather than guessed at: a discharge in
   * an unreadable unit leaves the step pending, and a time column in one is
   * dropped, because there is no pending state for time and every consumer
   * would otherwise fit a curve to the wrong axis. */
  var DISCHARGE_TEXT_RE = /discharge\s*(?:of|0f)?\s*[:=]?\s*(\d+(?:\.\d+)?)\s*([a-zµμ]{1,3}\s*3?\s*\/\s*[a-z]{1,4}|lps|lpm|lph)/ig;

  var STEP_LABEL_RE = /^\s*step\s*\d*\s*q\b/i;

  /* The heading a sheet prints over a column group - "Constant discharge
   * 61-120 min", "Recovery" - is the sheet's own statement of what the block
   * holds and which minutes of the test it covers, so both readings below
   * take the block's place in the test from it rather than from an
   * assumption. */
  var BLOCK_SPAN_RE = /(\d+(?:\.\d+)?)\s*(?:-|to)\s*(\d+(?:\.\d+)?)\s*([a-z]{1,8})?/i;

  /* What a column's own header says the column holds.
   *
   * "Recovery" is tested before "water level" so a column headed "Recovery
   * water level" is read as the recovery column it says it is, and "drawdown"
   * before "level" so an increment column is never taken for a level. */
  function columnRole(text) {
    if (!text) return '';
    if (text.indexOf('reco') >= 0) return 'recovery';
    if (text.indexOf('drawdown') >= 0 || text.indexOf('draw down') >= 0) {
      return 'drawdown';
    }
    if (text.indexOf('water') >= 0 || text.indexOf('level') === 0) return 'level';
    return '';
  }

  /* The minutes a block heading says the block covers, e.g. [61, 120].
   *
   * null when the heading names no span, or names one in a unit that cannot
   * be read: an offset applied to every reading in a block has to come from
   * the sheet, never from a guess at what "1-2" might mean. */
  function blockSpanMin(heading) {
    var match = BLOCK_SPAN_RE.exec(normaliseDashes(String(heading || '')));
    if (!match) return null;
    /** @type {number|null} */
    var first = parseFloat(match[1]);
    /** @type {number|null} */
    var last = parseFloat(match[2]);
    var written = (match[3] || '').trim();
    if (written) {
      first = convertUnit(first, written, 'min', 'time');
      last = convertUnit(last, written, 'min', 'time');
    }
    if (first === null || last === null || last <= first) return null;
    return [first, last];
  }

  /* The heading the sheet prints above a column group ("" when there is none).
   *
   * Only the two rows immediately above the column headers are read - on the
   * template the block headings sit directly over the group's own first
   * column - and only a heading the reader can act on is returned: one naming
   * the recovery block, or the minutes the block covers. Anything else
   * standing above the table belongs to the sheet's header block ("Discharge
   * per step (m3/h)" sits there on the template), and carrying that into a
   * flag as if the crew had written it over the readings would say more than
   * the sheet does. */
  function blockHeading(grid, headerRow, start, end) {
    for (var r = headerRow - 1; r > Math.max(headerRow - 3, -1); r--) {
      var row = (r < grid.length ? grid[r] : null) || [];
      for (var cc = start; cc < Math.min(end, row.length); cc++) {
        var text = cleanText(row[cc]);
        if (!text) continue;
        if (text.toLowerCase().indexOf('recover') >= 0 ||
            blockSpanMin(text) !== null) {
          return text;
        }
      }
    }
    return '';
  }

  /* One column group: the base fields the whole block shares, plus its own. */
  function pumpingGroup(base, level, kind) {
    return {
      time: base.time, time_header: base.time_header,
      block_heading: base.block_heading, level: level, kind: kind,
    };
  }

  /* Find the header row of Time / Water Level / ... column groups.
   *
   * Returns {row, groups}. Each group carries its column indices, the header
   * its time column declares, the heading printed above the block, and a
   * kind:
   *
   *   "pumping"             time and water level while the pump ran.
   *   "recovery"            time and water level after it stopped. A recovery
   *                         block's Drawdown and Recovery columns are
   *                         increments between readings, so the water level
   *                         column is the one read: a block laid out Time /
   *                         Level / Drawdown / Recovery used to have its
   *                         fourth column read as the levels, which made the
   *                         recovery curve the increment between readings
   *                         rather than the water level (ROADMAP
   *                         data-ingestion-10).
   *   "recovery_unreadable" a recovery column the sheet never explains.
   *                         pumpingFromGrid flags it and reads no curve from
   *                         it.
   *
   * A block is a recovery block when its heading or its time column says
   * "recovery", or when its columns run Time, Water Level[, Drawdown],
   * Recovery with nothing else between them. A recovery column that says it
   * holds water levels ("Recovery water level") is instead read as a second
   * series against the shared time column, which is the other layout the
   * sheets use. */
  function findGroups(grid) {
    var best = null;
    for (var r = 0; r < grid.length; r++) {
      var texts = rowText(grid[r]);
      var timeCols = [];
      for (var c = 0; c < texts.length; c++) {
        if (texts[c].indexOf('time') === 0) timeCols.push(c);
      }
      if (!timeCols.length) continue;
      var groups = [];
      for (var gi = 0; gi < timeCols.length; gi++) {
        var start = timeCols[gi];
        var end = gi + 1 < timeCols.length ? timeCols[gi + 1] : texts.length;
        /** @type {Record<string, number>} */
        var roles = {};
        for (var cc = start + 1; cc < end; cc++) {
          var role = columnRole(texts[cc]);
          if (role && !(role in roles)) roles[role] = cc;
        }
        var levelCol = 'level' in roles ? roles.level : null;
        var drawCol = 'drawdown' in roles ? roles.drawdown : null;
        var recoCol = 'recovery' in roles ? roles.recovery : null;
        if (levelCol === null && recoCol === null) continue;
        /* The header text travels with the group so the time unit it declares
         * - "Time (min)", "Time (h)" - is read rather than assumed, and the
         * block heading travels with it so a constant test's hourly blocks
         * can be put back in the order the sheet gives them. */
        var header = texts[start];
        var heading = blockHeading(grid, r, start, end);
        var base = { time: start, time_header: header, block_heading: heading };
        var saysRecovery = heading.toLowerCase().indexOf('recover') >= 0 ||
          header.indexOf('recover') >= 0;
        var recoSaysLevel = recoCol !== null &&
          (texts[recoCol].indexOf('level') >= 0 ||
           texts[recoCol].indexOf('water') >= 0);

        if (recoCol === null) {
          groups.push(pumpingGroup(base, levelCol,
            saysRecovery ? 'recovery' : 'pumping'));
        } else if (saysRecovery) {
          /* The sheet names the block, so its level column is the level and
           * its recovery column is an increment, as the drawdown column is on
           * a pumping block. */
          groups.push(pumpingGroup(base,
            levelCol === null ? recoCol : levelCol, 'recovery'));
        } else if (levelCol === null) {
          /* Nothing else in the block can be a water level, so the recovery
           * column is read as one. */
          groups.push(pumpingGroup(base, recoCol, 'recovery'));
        } else if (recoSaysLevel &&
            (timeCols.length === 1 || Math.max(levelCol, recoCol) - start > 2)) {
          /* A shared time column with a recovery column that says it holds
           * levels: two series read against the same times. A block with its
           * own time column and the recovery column beside it is a recovery
           * block, not a pumping block with a second series; read the other
           * way, its water levels were joined onto the drawdown curve as the
           * next hour. */
          groups.push(pumpingGroup(base, levelCol, 'pumping'));
          groups.push(pumpingGroup(base, recoCol, 'recovery'));
        } else if (Math.max(levelCol, recoCol) - start <= 2) {
          /* Time, Water Level, Recovery: the recovery block the bundled
           * template prints. */
          groups.push(pumpingGroup(base, levelCol, 'recovery'));
        } else if (levelCol === start + 1 && drawCol === start + 2 &&
                   recoCol === start + 3 && timeCols.length > 1) {
          /* Time, Level, Drawdown, Recovery: a recovery block written with
           * both increment columns. Reading its fourth column as the levels
           * made the recovery curve the rise between readings rather than the
           * water level (ROADMAP data-ingestion-10). It is read this way only
           * when another group holds the pumping readings; alone on a sheet
           * the same four columns could be a whole test against one time
           * column, which is refused below. */
          groups.push(pumpingGroup(base, levelCol, 'recovery'));
        } else {
          /* A recovery column standing apart from the block's own columns: it
           * may hold levels or increments and the sheet does not say which,
           * so the pumping pair is read and the recovery column is refused by
           * name. */
          groups.push(pumpingGroup(base, levelCol, 'pumping'));
          var refused = pumpingGroup(base, recoCol, 'recovery_unreadable');
          refused.recovery_header = cleanText((grid[r] || [])[recoCol]);
          groups.push(refused);
        }
      }
      if (groups.length && (best === null || groups.length > best.groups.length)) {
        best = { row: r, groups: groups };
      }
    }
    return best;
  }

  /* Returns {times, levels, unitText, skipped, clocks}. unitText is '' when
   * nothing was declared (minutes assumed) and '?<text>' when a unit was
   * declared that could not be read, in which case the caller drops the
   * group. clocks names the readings written as a clock, [index, as
   * written]: each is read as the elapsed time it shows (readTime). Read for
   * the first number in it, 01:30 was minute 1 and 00:05 minute 0. A date is
   * one of the skipped cells. */
  function readSeries(grid, headerRow, group) {
    var header = group.time_header || '';
    /* A unit the header declares applies to the whole column, so an
     * unreadable one there costs the group. A unit written into one cell
     * applies to that cell, so an unreadable one there costs one reading -
     * otherwise a single annotated entry threw away the test. */
    var declared = unitFromLabel(header, 'time');
    if (declared.written && !declared.unit) {
      return { times: [], levels: [], unitText: '?' + declared.written,
        skipped: [], clocks: [] };
    }
    var times = [], levels = [], skipped = [], clocks = [], unitText = declared.written;
    for (var r = headerRow + 1; r < grid.length; r++) {
      var row = grid[r] || [];
      var cell = group.time < row.length ? row[group.time] : null;
      var wl = group.level < row.length ? parseNumber(row[group.level]) : null;
      var read = readTime(cell, [header]);
      var quantity = read.quantity;
      if (quantity.status === 'absent' || wl === null) continue;
      if (quantity.status === 'unknown') {
        // never silent; a date as Python's str() writes it, a TRUE as Excel
        // shows it
        skipped.push(cell instanceof Date ? cleanText(cell)
          : typeof cell === 'boolean' ? quantity.unit_text : String(cell));
        continue;
      }
      if (read.clock) clocks.push([times.length, read.clock]);
      else if (quantity.unit_text) unitText = quantity.unit_text;
      times.push(quantity.value); levels.push(wl);
    }
    return { times: times, levels: levels, unitText: unitText, skipped: skipped,
      clocks: clocks };
  }

  /* The row's own leading label, e.g. "Discharge per step (m3/h)". */
  function rowUnitHint(row) {
    for (var i = 0; i < (row || []).length; i++) {
      var text = cleanText(row[i]);
      if (text && text.toLowerCase().indexOf('discharge') >= 0) return text;
    }
    return '';
  }

  /* Two hazards on a real sheet, both handled here: the rate is written in
   * whatever unit the crew used, and the neighbouring cell may be the NEXT
   * step's label rather than a value - scanning it blindly read
   * "Step 2 Q (m3/h)" as a discharge of 2 m3/h whenever the first step's box
   * was left empty, and fitted a transmissivity to it. */
  function findStepDischarges(grid) {
    var discharges = {};
    grid.forEach(function (row) {
      var hint = rowUnitHint(row);
      (row || []).forEach(function (cell, c) {
        var label = cleanText(cell);
        if (!STEP_LABEL_RE.test(label)) return;
        var num = parseNumber(label.toLowerCase().split('q')[0]);
        if (num === null) return;
        for (var cc = c + 1; cc < Math.min(c + 3, row.length); cc++) {
          if (STEP_LABEL_RE.test(cleanText(row[cc]))) break;
          var quantity = readQuantity(row[cc], [label, hint], 'flow');
          if (quantity.status === 'absent') continue;
          discharges[Math.trunc(num)] = quantity;
          break;
        }
      });
    });
    return discharges;
  }

  /* A note saying the discharge was not measured - "Not measured (step 1:
   * ...)", as the pumping test co-pilot writes it - is the crew's statement
   * that there is no rate, whatever its reason mentions: "a discharge of
   * 2 m3/h by eye" there was being read as the measured one. */
  var NOT_MEASURED_RE = /^\s*not\s+measured\b/i;

  /* Returns {values, unreadable}: a note whose unit cannot be read is
   * reported rather than converted, so it is raised as a flag instead of
   * quietly becoming a number in m3/h. */
  function dischargeCandidatesFromText(grid) {
    var found = [], unreadable = [];
    grid.forEach(function (row) {
      (row || []).forEach(function (cell) {
        if (cell === null || cell === undefined || typeof cell === 'number') return;
        var text = String(cell), m;
        if (NOT_MEASURED_RE.test(text)) return;
        DISCHARGE_TEXT_RE.lastIndex = 0;
        while ((m = DISCHARGE_TEXT_RE.exec(text)) !== null) {
          var written = m[2].trim();
          var value = convertUnit(parseFloat(m[1]), written, 'm3/h', 'flow');
          if (value === null) {
            if (unreadable.indexOf(written) < 0) unreadable.push(written);
            continue;
          }
          if (found.indexOf(value) < 0) found.push(value);
        }
      });
    });
    return { values: found, unreadable: unreadable };
  }

  /* Pre-printed text that names a test kind without recording which test was
   * run: the template's own title mentions both, and its constant-discharge
   * column labels sit on every sheet whatever was pumped. Reading either as an
   * answer turned step tests into constant ones. */
  var CONSTANT_COLUMN_LABEL_RE = /constant\s+discharge\s*\d/;

  function sheetTestType(grid) {
    for (var r = 0; r < grid.length; r++) {
      var row = grid[r] || [];
      for (var c = 0; c < row.length; c++) {
        var text = cleanText(row[c]).toLowerCase();
        if (!text) continue;
        var stepWords = text.indexOf('step test') >= 0 || text.indexOf('step drawdown') >= 0;
        var constantWords = text.indexOf('constant discharge') >= 0 ||
          text.indexOf('constant rate') >= 0;
        if (constantWords && text.indexOf('step') >= 0) continue;
        if (stepWords) return 'step';
        if (constantWords && !CONSTANT_COLUMN_LABEL_RE.test(text)) return 'constant';
      }
    }
    return '';
  }

  /* What a joined series is called, for the constant discharge readings and
   * the recovery: [readings, what a block's minutes count from, an example
   * heading] (pumping.py _BLOCK_SERIES). */
  var BLOCK_SERIES = {
    constant: ['constant discharge readings', 'test', 'Constant discharge 121-180 min'],
    recovery: ['recovery readings', 'recovery', 'Recovery 61-120 min'],
  };

  /* Join the hourly blocks of a constant discharge test, or of a recovery,
   * into one series.
   *
   * A constant discharge sheet is written in hourly column groups side by
   * side and each group's elapsed time is often counted within its own hour:
   * 1, 2, 3 in the first block and 1, 2, 3 again in the second. Concatenating
   * the groups and sorting the result interleaved them into a sawtooth -
   * minute 1 of every hour, then minute 2 of every hour - and every drawdown
   * curve and every transmissivity fitted to it was wrong (ROADMAP
   * data-ingestion-10). A long recovery is written the same way, and only
   * its first block used to be read, without a word.
   *
   * Each block's place in the series is read off the sheet: the minutes its
   * own heading names ("Constant discharge 61-120 min"), or, when the heading
   * names none, the last reading of the block before it, which is what a
   * block whose times go backwards continues from. A block that is neither -
   * one starting inside the readings already taken and running past them - is
   * left out and named, because a block placed at a minute nobody can check
   * produces a curve nobody can trust.
   *
   * series is 'constant' or 'recovery', for the sentences. Returns {times,
   * levels, joined, dropped}; joined and dropped are sentences naming what
   * was done, for the caller to raise as flags. */
  function joinBlocks(blocks, series) {
    var names = BLOCK_SERIES[series || 'constant'];
    var readings = names[0], what = names[1];
    var times = [], levels = [], joined = [], dropped = [], end = null;
    blocks.forEach(function (block, index) {
      var number = index + 1;
      var t = block.times, wl = block.levels;
      var heading = String(block.group && block.group.block_heading || '');
      var span = blockSpanMin(heading);
      var first = t[0];
      var last = arrMax(t);
      var offset = 0;
      /* The note is held until the block is actually kept. Pushed here, a
       * block that the backwards guard below then drops was named twice:
       * the warning said it was left out and the info flag said how many
       * minutes had been added to it. */
      var note = '';
      if (span !== null && first < span[0]) {
        /* The block is placed by its heading alone. The template numbers the
         * minutes of each block on from the block before ("0-60 min",
         * "61-120 min"), so the block's own clock reads zero one minute before
         * its heading starts. Aligning its first reading with the heading
         * instead put a block read every five minutes, 5 to 60, at 61 to 116,
         * and a four-hour test ended at 226 minutes. */
        offset = Math.max(span[0] - 1.0, 0.0);
        if (offset) {
          note = phrase('pumping.block_by_heading', { number: number, heading: heading,
            start: span[0], end: span[1], offset: offset, first: first,
            placed: first + offset, what: what });
        }
      } else if (span !== null || end === null || first > end) {
        offset = 0;
      } else if (last <= end) {
        offset = end;
        note = phrase('pumping.block_continued', { number: number, first: first,
          end: end, offset: offset });
      } else {
        dropped.push(phrase('pumping.block_ambiguous', { number: number,
          readings: readings, first: first, end: end, last: last, what: what }));
        return;
      }
      var shifted = t.map(function (v) { return v + offset; });
      if (end !== null && shifted[0] < end) {
        dropped.push(phrase('pumping.block_backwards', { number: number,
          readings: readings, placed: shifted[0], end: end }));
        return;
      }
      if (note) joined.push(note);
      times = times.concat(shifted);
      levels = levels.concat(wl);
      end = arrMax(shifted);
    });
    var order = times.map(function (v, i) { return i; })
      .sort(function (a, b) { return times[a] - times[b] || a - b; });
    return {
      times: order.map(function (i) { return times[i]; }),
      levels: order.map(function (i) { return levels[i]; }),
      joined: joined, dropped: dropped,
    };
  }

  /* joinBlocks, with what it did raised as flags: {times, levels, flags}
   * (pumping.py _join_flags). */
  function joinFlags(blocks, series) {
    var names = BLOCK_SERIES[series];
    var joinedBlocks = joinBlocks(blocks, series);
    var flags = joinedBlocks.dropped.map(function (note) {
      return { level: 'warning', code: series + '_block_unreadable',
        message: phrase('pumping.block_left_out', { note: note, example: names[2] }) };
    });
    if (joinedBlocks.joined.length && joinedBlocks.times.length) {
      flags.push({ level: 'info', code: series + '_blocks_joined',
        message: phrase('pumping.blocks_joined', { readings: names[0],
          count: blocks.length, notes: joinedBlocks.joined.join('; '),
          first: arrMin(joinedBlocks.times), last: arrMax(joinedBlocks.times) }) });
    }
    return { times: joinedBlocks.times, levels: joinedBlocks.levels, flags: flags };
  }

  /* Words in a recovery block's time header or heading that say its times
   * count from the pump stopping: "Time since pump stopped", "after
   * shut-off", "since pump off"; "since start" does not (pumping.py
   * _SINCE_STOP_RE). */
  var SINCE_STOP_RE = /stop|shut|\boff\b/;

  /* A value cell whose text starts as a number does: "8", "50 mm", "-2". */
  var STARTS_AS_NUMBER_RE = /^\s*[-+]?\.?[0-9]/;

  /* The casing and riser diameters the sheet records, in inches, from what
   * extractHeaderFields found; a diameter with no unit, or none the toolkit
   * reads, is refused with a flag (pumping.py _diameters). */
  function sheetDiameters(found, flags) {
    var out = {};
    [['casing_diameter_in', 'casing'], ['riser_diameter_in', 'riser']].forEach(function (k) {
      if (!Object.prototype.hasOwnProperty.call(found, k[0])) return;
      var label = found[k[0]][0], value = found[k[0]][1];
      /* text that does not start with a number is the next label or a note
       * standing where the value would be, not a diameter: with the
       * co-pilot's riser left blank, the "Planned rate (m3/h)" label under it
       * was read as a riser of 3 inches (pumping.py _diameters) */
      if (typeof value === 'string' && !STARTS_AS_NUMBER_RE.test(value)) return;
      var quantity = typeof value === 'number' || typeof value === 'string'
        ? readQuantity(value, [label], 'length')
        : { value: null, raw_value: null, unit_text: '', status: 'unknown', dimension: 'length' };
      if (quantity.status === 'absent') return;
      if (quantity.status === 'unknown' || quantity.status === 'assumed' ||
          quantity.value === null || !(quantity.value > 0)) {
        flags.push({ level: 'warning', code: 'diameter_unreadable',
          message: phrase('pumping.diameter_unreadable', { what: k[1],
            written: cleanText(value) }) });
        return;
      }
      var unit = parseUnit(quantity.unit_text, 'length');
      out[k[0]] = unit && unit.canonical === 'in' ? Number(quantity.raw_value)
        : quantity.value / 0.0254;
    });
    /* a casing no wider than its riser leaves no casing storage at all: a
     * slip on the sheet, not a borehole (pumping.py _diameters) */
    if (out.casing_diameter_in !== undefined && out.riser_diameter_in !== undefined &&
        out.casing_diameter_in <= out.riser_diameter_in) {
      flags.push({ level: 'warning', code: 'diameters_inconsistent',
        message: phrase('pumping.diameters_inconsistent', {
          casing: out.casing_diameter_in, riser: out.riser_diameter_in }) });
      return {};
    }
    return out;
  }

  /**
   * @param {Grid} grid
   * @param {string} [source]
   * @returns {PumpingTest}
   */
  function pumpingFromGrid(grid, source) {
    /** @type {Record<string, Array<*>>} */
    var found = {};
    var fields = extractHeaderFields(grid, grid.length, found);
    var site = siteFromFields(fields, source);
    var flags = [];
    var located = findGroups(grid);
    if (!located) {
      throw new Error('No Time/Water Level column groups found in ' + (source || 'the sheet'));
    }

    /* The sheet carries a recovery column but never says what is in it, and a
     * recovery curve drawn from increments is wrong by the whole depth to
     * water. Refusing it and naming it is the only honest answer (ROADMAP
     * data-ingestion-10). */
    located.groups.forEach(function (g) {
      if (g.kind !== 'recovery_unreadable') return;
      var where = g.block_heading
        ? " in the '" + g.block_heading + "' block" : '';
      flags.push({
        level: 'warning', code: 'recovery_layout_unreadable',
        message: "A column headed '" + (g.recovery_header || '') + "' stands " +
          'apart from the water level column' + where + ', and nothing on the ' +
          'sheet says whether it holds water levels or the rise between ' +
          'readings, so no recovery curve was read from it. Head the recovery ' +
          "block 'Recovery', or the column 'Recovery water level (m)'.",
      });
    });

    /* A time column whose unit cannot be read is dropped rather than taken as
     * minutes: reading hours as minutes would rescale every drawdown curve
     * and every transmissivity fitted to it, silently. */
    function seriesOfKind(kind) {
      var out = [];
      /** @type {Rec} */ (located).groups.forEach(function (g) {
        if (g.kind !== kind) return;
        var series = readSeries(grid, /** @type {Rec} */ (located).row, g);
        if (series.unitText.indexOf('?') === 0) {
          flags.push({
            level: 'error', code: 'time_unit_unknown',
            message: 'The ' + kind + " time column is headed '" +
              (g.time_header || '') + "' and its unit '" +
              series.unitText.slice(1) + "' could not be read, so the readings " +
              'were not used. Head the column in minutes, hours or seconds.',
          });
          return;
        }
        if (series.unitText &&
            ['min', 'mins', 'minute', 'minutes'].indexOf(
              series.unitText.toLowerCase()) < 0) {
          flags.push({
            level: 'info', code: 'time_unit_converted',
            message: 'The ' + kind + " times are recorded in '" +
              series.unitText + "' and have been converted to minutes for the " +
              'analysis.',
          });
        }
        if ((series.skipped || []).length) {
          flags.push({
            level: 'warning', code: 'time_reading_unreadable',
            message: series.skipped.length + ' ' + kind + ' reading(s) carried ' +
              'text this toolkit could not read as a time and were left out (' +
              series.skipped.slice(0, 3).map(function (x) {
                return "'" + x + "'";
              }).join(', ') + '). Put notes outside the reading columns.',
          });
        }
        /* Each block is handed back with the group it came from, because a
         * constant test's blocks are placed by the heading the sheet prints
         * over them before they are joined into one series, and with the
         * readings in it written as a clock. */
        if (series.times.length) {
          series.group = g;
          out.push(series);
        }
      });
      return out;
    }

    var pumpingSeries = seriesOfKind('pumping');
    var recoverySeries = seriesOfKind('recovery');

    /* A test's first reading is taken in its first hour, so an earliest
     * pumping reading written as a clock past it, 08:05, is a time of day,
     * and the sheet is refused rather than read as a test that began eight
     * hours in. A block whose heading names its minutes is held to its
     * heading instead. The earliest reading, not the first row: rows written
     * out of order put a later reading at the top (pumping.py _assemble). */
    if (pumpingSeries.length) {
      var block0 = pumpingSeries[0];
      var span0 = blockSpanMin(String(block0.group.block_heading || ''));
      var earliest = 0;
      for (var e = 1; e < block0.times.length; e++) {
        if (block0.times[e] < block0.times[earliest]) earliest = e;
      }
      var t0 = block0.times[earliest];
      var clock0 = block0.clocks.filter(function (/** @type {Array<*>} */ c) {
        return c[0] === earliest;
      })[0];
      if (clock0 && clockFormat([block0.group.time_header || '']) === 'hm' &&
          t0 > 60.0 && (span0 === null || t0 > span0[1])) {
        flags.push({ level: 'error', code: 'time_of_day',
          message: phrase('pumping.time_of_day', { example: clock0[1] }) });
        pumpingSeries = [];
        recoverySeries = [];
      }
    }

    [['pumping', pumpingSeries, 'started'], ['recovery', recoverySeries, 'stopped']]
      .forEach(function (kind) {
        var read = [];
        /** @type {Rec[]} */ (kind[1]).forEach(function (series) {
          series.clocks.forEach(function (/** @type {Array<*>} */ c) {
            read.push([series.times[c[0]], c[1],
              clockFormat([series.group.time_header || ''])]);
          });
        });
        if (read.length) {
          flags.push({ level: 'info', code: 'time_clock_read',
            message: phrase('pumping.time_clock_read', { count: read.length,
              kind: kind[0], format: phraseTable('pumping.time_clock_formats')[read[0][2]],
              event: kind[2], example: read[0][1], minutes: read[0][0] }) });
        }
      });

    var testType = String(fields.test_type || '').trim().toLowerCase();
    var stated = !!testType;
    if (!testType) testType = sheetTestType(grid);
    var inferredFromShape = !testType;
    if (!testType) testType = pumpingSeries.length > 1 ? 'step' : 'constant';
    if (inferredFromShape && !stated && pumpingSeries.length > 1) {
      flags.push({
        level: 'info', code: 'test_type_inferred',
        message: 'The test type cell is blank; the ' + pumpingSeries.length +
          ' filled column groups have been read as the steps of a step test. ' +
          'If this was a constant discharge test, write "constant" in the test ' +
          'type cell so the readings are analysed as one series.',
      });
    }

    if (testType.indexOf('constant') === 0 && pumpingSeries.length > 1) {
      /* The hourly column groups are one continuous series on a constant
       * test, but each block's times are often counted within its own hour,
       * so every block is put back in its place before they are joined. */
      var joinedBlocks = joinFlags(pumpingSeries, 'constant');
      Array.prototype.push.apply(flags, joinedBlocks.flags);
      pumpingSeries = joinedBlocks.times.length
        ? [{ times: joinedBlocks.times, levels: joinedBlocks.levels }] : [];
    }

    /* A recovery written in blocks is joined by the same rules. */
    var recoveryTime = null, recoveryLevel = null;
    if (recoverySeries.length > 1) {
      var joinedRecovery = joinFlags(recoverySeries, 'recovery');
      Array.prototype.push.apply(flags, joinedRecovery.flags);
      if (joinedRecovery.times.length) {
        recoveryTime = joinedRecovery.times;
        recoveryLevel = joinedRecovery.levels;
      }
    } else if (recoverySeries.length) {
      recoveryTime = recoverySeries[0].times;
      recoveryLevel = recoverySeries[0].levels;
    }

    /* The length of each step is read in the unit its label or its own cell
     * names: "1 hr" was a step of 1 minute. */
    var stepLength = null;
    if (Object.prototype.hasOwnProperty.call(found, 'step_length_min')) {
      var lengthRead = readTime(found.step_length_min[1], [found.step_length_min[0]]);
      if (lengthRead.quantity.status === 'unknown') {
        flags.push({ level: 'warning', code: 'step_length_unreadable',
          message: phrase('pumping.step_length_unreadable', {
            written: cleanText(found.step_length_min[1]) }) });
      } else if (lengthRead.quantity.value !== null && lengthRead.quantity.value > 0) {
        stepLength = lengthRead.quantity.value;
      }
    }
    var diameters = sheetDiameters(found, flags);

    var discharges = findStepDischarges(grid);
    var steps = pumpingSeries.map(function (s, i) {
      var quantity = discharges[i + 1];
      /* A refused unit leaves this null, which is the existing "results
       * pending until discharge is supplied" path - the right answer, and far
       * better than a number in the wrong unit. */
      return {
        step_number: i + 1, time_min: s.times, water_level_m: s.levels,
        discharge_m3_per_h: quantity === undefined ? null : quantity.value,
        label: pumpingSeries.length > 1 ? ('Step ' + (i + 1)) : 'Pumping phase',
      };
    });
    steps.forEach(function (step, i) {
      var quantity = discharges[i + 1];
      if (quantity === undefined) return;
      if (quantity.status === 'unknown') {
        flags.push({ level: 'warning', code: 'discharge_unit_unknown',
          message: 'Step ' + (i + 1) + ' discharge is written as ' +
            formatG(quantity.raw_value) + " '" + quantity.unit_text +
            "', a unit this toolkit does not recognise, so it was not used. " +
            'Record the rate in m3/h, L/s or L/min.' });
      } else if (quantity.status === 'converted') {
        flags.push({ level: 'info', code: 'discharge_unit_converted',
          message: 'Step ' + (i + 1) + ' discharge ' +
            formatG(quantity.raw_value) + ' ' + quantity.unit_text +
            ' read as ' + formatG(quantity.value, 3) + ' m3/h.' });
      } else if (quantity.status === 'assumed') {
        flags.push({ level: 'info', code: 'discharge_unit_assumed',
          message: 'Step ' + (i + 1) + ' discharge ' +
            formatG(quantity.raw_value) + ' carries no unit on the sheet and ' +
            'was read as m3/h. Head the discharge row with its unit to remove ' +
            'the assumption.' });
      }
    });

    /* Free-text discharge: use it only when unambiguous. */
    var fromText = dischargeCandidatesFromText(grid);
    var candidates = fromText.values;
    var missing = steps.filter(function (s) { return s.discharge_m3_per_h === null; });
    fromText.unreadable.forEach(function (written) {
      flags.push({ level: 'warning', code: 'discharge_unit_unknown',
        message: "A discharge note on the sheet is written in '" + written +
          "', a unit this toolkit does not recognise, so it was not used." });
    });
    if (candidates.length && missing.length) {
      if (candidates.length === 1 && steps.length === 1) {
        steps[0].discharge_m3_per_h = candidates[0];
        flags.push({ level: 'info', code: 'discharge_from_text',
          message: 'Discharge ' + formatG(candidates[0]) + ' m3/h taken from a ' +
            'text note on the sheet; confirm against the measured value.' });
      } else {
        flags.push({ level: 'warning', code: 'discharge_ambiguous',
          message: 'Discharge mentioned in sheet text (' +
            candidates.map(function (c) { return formatG(c) + ' m3/h'; }).join(', ') +
            ') but not assigned per step; enter values in the template.' });
      }
    }

    if (recoveryTime !== null) testType += '+recovery';

    var swl = fields.static_water_level_m === undefined ? null : fields.static_water_level_m;
    /* on the test's clock: a step test whose times restart each step pumped
     * for its steps' lengths added, not for its longest step */
    var stepOffsets = stepOffsetsMin(steps);
    var pumpingDuration = steps.length
      ? arrMax(steps.map(function (s, i) { return arrMax(s.time_min) + stepOffsets[i]; }))
      : null;

    /* Recovery times written on the test's clock - 241, 242 after a
     * 240-minute test - were taken as minutes since the pump stopped. A
     * recovery whose first reading comes at or after the minute the pump
     * stopped is on the test's clock unless its header says it counts from
     * the stop, and is moved back by the pumping time (pumping.py). */
    if (recoveryTime !== null && pumpingDuration !== null && recoveryTime.length) {
      var firstRecovery = arrMin(recoveryTime);
      var saysSince = recoverySeries.some(function (s) {
        return SINCE_STOP_RE.test((String(s.group.time_header || '') + ' ' +
          String(s.group.block_heading || '')).toLowerCase());
      });
      if (!saysSince && firstRecovery >= pumpingDuration) {
        var stopped = pumpingDuration;
        recoveryTime = recoveryTime.map(function (v) { return v - stopped; });
        flags.push({ level: 'info', code: 'recovery_on_test_clock',
          message: phrase('pumping.recovery_on_test_clock', { first: firstRecovery,
            duration: pumpingDuration }) });
      }
    }

    /** @type {PumpingTest} */
    var test = {
      site: site, borehole_ref: String(fields.borehole_ref || ''),
      test_type: testType, static_water_level_m: swl,
      borehole_depth_m: fields.borehole_depth_m === undefined ? null : fields.borehole_depth_m,
      pump_setting_m: fields.pump_setting_m === undefined ? null : fields.pump_setting_m,
      step_length_min: stepLength,
      steps: steps, recovery_time_min: recoveryTime, recovery_level_m: recoveryLevel,
      pumping_duration_min: pumpingDuration, source: String(source || ''), flags: [],
      casing_diameter_in: diameters.casing_diameter_in === undefined
        ? null : diameters.casing_diameter_in,
      riser_diameter_in: diameters.riser_diameter_in === undefined
        ? null : diameters.riser_diameter_in,
    };

    if (swl === null) {
      flags.push({ level: 'error', code: 'missing_static_water_level',
        message: 'Static water level is missing; drawdown cannot be computed.' });
    }
    var missingQ = steps.filter(function (s) { return s.discharge_m3_per_h === null; })
      .map(function (s) { return s.step_number; });
    if (missingQ.length) {
      /* every result is pending only when no step has a rate */
      flags.push({ level: 'warning', code: 'missing_discharge',
        message: phrase(missingQ.length === steps.length ? 'pumping.missing_discharge'
          : 'pumping.missing_discharge_some', { steps: missingQ.join(', ') }) });
    }
    if (swl !== null) {
      /* The recovery limb is checked too: a recovery that overshoots the
       * static level gives negative residual drawdown, and the recovery
       * transmissivity - the one the yield prefers - is fitted through it. */
      var above = [];
      if (steps.length && steps.some(function (s) {
        return s.water_level_m.some(function (v) { return v < swl - 0.01; });
      })) above.push('pumping');
      if (recoveryLevel && recoveryLevel.some(function (v) { return v < swl - 0.01; })) {
        above.push('recovery');
      }
      if (above.length) {
        flags.push({ level: 'warning', code: 'water_level_above_static',
          message: 'Some ' + above.join(' and ') + ' water levels are above the ' +
            'stated static water level, giving negative drawdown. Check the ' +
            'static level and the measuring datum on the sheet.' });
      }
    }
    steps.forEach(function (s) {
      for (var i = 1; i < s.time_min.length; i++) {
        if (s.time_min[i] - s.time_min[i - 1] <= 0) {
          flags.push({ level: 'warning', code: 'time_not_increasing',
            message: 'Times are not strictly increasing in ' + s.label + '.',
            context: s.label });
          break;
        }
      }
    });
    if (test.borehole_depth_m && test.pump_setting_m &&
        test.pump_setting_m > test.borehole_depth_m) {
      flags.push({ level: 'warning', code: 'pump_below_borehole',
        message: 'Pump setting is deeper than the borehole depth.' });
    }
    if (test.borehole_depth_m && steps.length) {
      var maxWl = arrMax(steps.map(function (s) {
        return arrMax(s.water_level_m.filter(isFinite));
      }));
      if (maxWl > test.borehole_depth_m) {
        flags.push({ level: 'warning', code: 'level_below_borehole',
          message: 'Recorded water level ' + pyFixed(maxWl, 2) + ' m exceeds the ' +
            'stated borehole depth ' + pyFixed(test.borehole_depth_m, 0) +
            ' m; check the sheet.' });
      }
    }
    if (test.pump_setting_m && steps.length) {
      /* A pump cannot draw the water below its own intake. Levels 18 m under
       * the pump went into a report as 59 m of drawdown and 38 m of available
       * drawdown, with nothing to say the sheet could not be right. */
      var maxWlPump = arrMax(steps.map(function (s) {
        return arrMax(s.water_level_m.filter(isFinite));
      }));
      if (maxWlPump > test.pump_setting_m) {
        flags.push({ level: 'warning', code: 'level_below_pump',
          message: 'Recorded water level ' + pyFixed(maxWlPump, 2) + ' m is below ' +
            'the pump intake at ' + pyFixed(test.pump_setting_m, 0) + ' m. A pump ' +
            'cannot draw the level below its own intake, so the pump setting, ' +
            'the levels or the datum on the sheet is wrong; the drawdown ' +
            'figures are as recorded and not to be relied on.' });
      }
    }
    test.flags = flags;
    return test;
  }

  Object.assign(C, {
    cleanText: cleanText, parseNumber: parseNumber, isWholeNumber: isWholeNumber,
    parseDepthInterval: parseDepthInterval,
    matchLabel: matchLabel, matchLabelPriority: matchLabelPriority,
    splitInlineValue: splitInlineValue, extractHeaderFields: extractHeaderFields,
    siteFromFields: siteFromFields, rowText: rowText,
    soundingFromGrid: soundingFromGrid, readVesSheets: readVesSheets,
    drillingFromGrid: drillingFromGrid, qualityFromGrid: qualityFromGrid,
    pumpingFromGrid: pumpingFromGrid, parseInstalledScreens: parseInstalledScreens,
    normaliseDashes: normaliseDashes,
    parseWaterStrikeDepths: parseWaterStrikeDepths,
    headerLengthUnit: headerLengthUnit, FOOT_M: FOOT_M,
    DRILLING_UNREADABLE: DRILLING_UNREADABLE, DRILLING_REFUSALS: DRILLING_REFUSALS,
    parseBitDiameterIn: parseBitDiameterIn,
    parsePenetrationRateMPerMin: parsePenetrationRateMPerMin,
    overlapDiscrepancies: overlapDiscrepancies, overlapRatios: overlapRatios,
    OVERLAP_DISCREPANCY_RATIO: OVERLAP_DISCREPANCY_RATIO,
    LABEL_PATTERNS: LABEL_PATTERNS,
  });

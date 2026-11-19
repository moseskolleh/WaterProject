
  /* =============================================================== units
   * groundwater/units.py. Every number read off a sheet arrives beside a
   * unit written by hand, and until now those units were decoration: a
   * laboratory result was compared against a guideline whatever unit each
   * carried, and a discharge was taken as m3/h whatever the sheet said.
   * Both are silent, order-of-magnitude errors - 5 ug/L of arsenic is a
   * fifth of the guideline, read as mg/L it is five hundred times over it.
   * So units are parsed, not assumed, and an unreadable one is refused.
   *
   * Bases: concentration mg/L, conductivity uS/cm, turbidity NTU, microbial
   * CFU/100 mL, flow m3/h, time min, length m.
   */

  var CANONICAL_UNITS = {
    concentration: 'mg/L', conductivity: 'uS/cm', turbidity: 'NTU',
    microbial: 'CFU/100 mL', ph: 'pH units', temperature: 'deg C',
    flow: 'm3/h', time: 'min', length: 'm',
  };

  /* Spellings that name a real quantity without pinning it down. Guessing at
   * one of these is exactly the failure this section exists to prevent. */
  var AMBIGUOUS_UNITS = {
    gpm: 1, gph: 1, 'gal/min': 1, 'gal/h': 1, ppt: 1, jtu: 1,
  };

  /** @type {Array<[RegExp, string]>} */
  var UNIT_CHAR_FIXES = [
    [/µ/g, 'u'], [/μ/g, 'u'], [/³/g, '3'], [/²/g, '2'],
    [/°/g, 'deg '], [/º/g, 'deg '], [/⁄/g, '/'], [/’/g, ''],
  ];

  /**
   * @param {*} text
   * @returns {string}
   */
  function normaliseUnit(text) {
    var s = String(text === null || text === undefined ? '' : text);
    /* "Nº/100 mL" and "N°/100 mL" are "No./100 mL" with the numero sign; the
     * sign would otherwise read as a degree (units.py _normalise) */
    s = s.replace(/(?<![A-Za-z0-9_])[nN][º°](?=\s*(?:\/|[pP][eE][rR]\b))/g, 'no');
    UNIT_CHAR_FIXES.forEach(function (pair) { s = s.replace(pair[0], pair[1]); });
    /* an en dash, an em dash and the minus sign (U+2212) are a hyphen */
    s = s.toLowerCase().trim().replace(/[–—−]/g, '-');
    s = s.replace(/\bper\b/g, '/');
    s = s.replace(/\bmilli\s*lit(re|er)s?\b|\bmillilit(re|er)s?\b/g, 'ml');
    s = s.replace(/\blit(re|er)s?\b/g, 'l');
    s = s.replace(/\bmet(re|er)s?\b/g, 'm');
    s = s.replace(/\bcubic\s*m\b/g, 'm3');
    s = s.replace(/\bminutes?\b|\bmins\b/g, 'min');
    s = s.replace(/\bseconds?\b|\bsecs\b/g, 's');
    s = s.replace(/\bhours?\b|\bhrs\b/g, 'h');
    s = s.replace(/\bdays?\b/g, 'd');
    s = s.replace(/\bdegrees?\b|\bdeg\b/g, 'deg ');
    s = s.replace(/\bcelsius\b|\bcentigrade\b/g, 'c');
    s = s.replace(/\./g, '');
    /* "/100 mL", "No./100 mL" and "per 100 mL" are "/100ml" written with a
     * space (units.py _normalise): an E. coli count of 12 per 100 mL was a
     * unit nobody could read, while "Absent" in the same unit passed. */
    s = s.replace(/(\d)\s+(m?l)\b/g, '$1$2');
    /* "-", "n/a" and friends are how a sheet writes "no unit here", not a
     * unit. Reading "-" as pH units made every non-pH row carrying the
     * ordinary blank marker unevaluable. */
    if (['-', '--', 'n/a', 'na', 'none', 'nil', '?'].indexOf(s) >= 0) return '';
    s = s.replace(/\s+/g, ' ').trim().replace(/\s*\/\s*/g, '/');
    return s;
  }

  var UNIT_BASIS_RE = /\bas\s+([a-z0-9().-]+)\s*$/;
  /* The spellings of nitrogen as a basis: "as N", "as NO3-N", "as nitrogen".
   * They are one basis, so "mg/L as NO3-N" is the same scale as "mg/L as N"
   * (units.py _NITROGEN_BASIS_RE). */
  var NITROGEN_BASIS_RE = /^(?:(?:no3|no2|nh4|nh3)-{0,2}n|nitrogen)$/;

  function splitUnitBasis(text) {
    var m = UNIT_BASIS_RE.exec(text);
    if (!m) return [text, ''];
    var basis = m[1].replace(/\s+/g, '');
    if (NITROGEN_BASIS_RE.test(basis)) basis = 'n';
    return [text.slice(0, m.index).trim(), basis];
  }

  /** The ion a unit's nitrogen basis names: "mg/L as NO3-N" -> "no3"; '' for
   * "as N", "as nitrogen", another basis or none. "as NO3-N" and "as NH4-N"
   * are one scale, nitrogen, so parseUnit reads both as the basis "n"; which
   * ion's nitrogen they mean is a separate question, and a nitrite row in
   * "mg/L as NO3-N" contradicts its unit (units.py nitrogen_species).
   * @param {*} text a written unit
   * @returns {string}
   */
  function nitrogenSpecies(text) {
    var m = UNIT_BASIS_RE.exec(normaliseUnit(text));
    if (!m) return '';
    var species = /^(no3|no2|nh4|nh3)-{0,2}n$/.exec(m[1].replace(/\s+/g, ''));
    return species ? species[1] : '';
  }

  var UNIT_TABLE = {};

  function registerUnit(canonical, dimension, factor, spellings, offset) {
    spellings.forEach(function (spelling) {
      UNIT_TABLE[normaliseUnit(spelling)] = {
        canonical: canonical, dimension: dimension, factor: factor,
        offset: offset || 0.0,
      };
    });
  }

  registerUnit('mg/L', 'concentration', 1.0,
    ['mg/l', 'milligrams/l', 'mg per l', 'mg/dm3', 'ppm', 'parts per million',
      'g/m3']);
  registerUnit('ug/L', 'concentration', 1e-3,
    ['ug/l', 'µg/l', 'μg/l', 'mcg/l', 'ppb', 'parts per billion',
      'mg/m3']);
  registerUnit('ng/L', 'concentration', 1e-6, ['ng/l']);
  registerUnit('g/L', 'concentration', 1e3, ['g/l', 'g/dm3', 'kg/m3']);
  registerUnit('mg/mL', 'concentration', 1e3, ['mg/ml']);
  registerUnit('uS/cm', 'conductivity', 1.0,
    ['us/cm', 'µs/cm', 'μs/cm', 'umho/cm', 'umhos/cm',
      'micro siemens/cm']);
  registerUnit('mS/cm', 'conductivity', 1e3, ['ms/cm', 'mmho/cm', 'mmhos/cm']);
  registerUnit('mS/m', 'conductivity', 10.0, ['ms/m']);
  registerUnit('S/m', 'conductivity', 1e4, ['s/m']);
  /* NTU, FNU and FTU are numerically interchangeable by convention; JTU is
   * not, and is refused above rather than converted. */
  registerUnit('NTU', 'turbidity', 1.0, ['ntu', 'fnu', 'ftu', 'nephelometric']);
  registerUnit('CFU/100 mL', 'microbial', 1.0,
    ['cfu/100ml', 'mpn/100ml', '/100ml', '#/100ml',
      'count/100ml', 'counts/100ml', 'no/100ml', 'cfu/100cm3']);
  registerUnit('CFU/mL', 'microbial', 100.0, ['cfu/ml', 'mpn/ml', 'count/ml']);
  registerUnit('CFU/L', 'microbial', 0.1, ['cfu/l', 'mpn/l', 'count/l']);
  registerUnit('pH units', 'ph', 1.0,
    ['ph units', 'ph unit', 'ph', 'su', 'standard units']);
  /* "oC" is the degree sign typed as a letter o */
  registerUnit('deg C', 'temperature', 1.0, ['deg c', 'c', '°c', 'degc',
    'celsius', 'oc']);
  registerUnit('deg F', 'temperature', 5.0 / 9.0, ['deg f', 'f', '°f',
    'degf'], -32.0 * 5.0 / 9.0);
  registerUnit('m3/h', 'flow', 1.0,
    ['m3/h', 'm3/hr', 'm³/h', 'cum/h', 'cubic m/h', 'm3 h-1']);
  registerUnit('m3/d', 'flow', 1.0 / 24.0, ['m3/d', 'm3/day', 'cum/d']);
  registerUnit('m3/min', 'flow', 60.0, ['m3/min']);
  registerUnit('m3/s', 'flow', 3600.0, ['m3/s']);
  registerUnit('L/s', 'flow', 3.6, ['l/s', 'lps', 'l s-1']);
  registerUnit('L/min', 'flow', 0.06, ['l/min', 'lpm', 'l/m']);
  registerUnit('L/h', 'flow', 1e-3, ['l/h', 'lph']);
  registerUnit('L/d', 'flow', 1e-3 / 24.0, ['l/d', 'l/day']);
  registerUnit('min', 'time', 1.0, ['min', 'mins', 'minute']);
  registerUnit('s', 'time', 1.0 / 60.0, ['s', 'sec']);
  registerUnit('h', 'time', 60.0, ['h', 'hr']);
  registerUnit('d', 'time', 1440.0, ['d', 'day']);
  registerUnit('m', 'length', 1.0, ['m', 'metre']);
  registerUnit('cm', 'length', 0.01, ['cm']);
  registerUnit('mm', 'length', 1e-3, ['mm']);
  registerUnit('ft', 'length', 0.3048, ['ft', 'feet', 'foot']);
  registerUnit('in', 'length', 0.0254, ['in', 'inch', 'inches', '"']);

  /* A unit string alone cannot tell metres from minutes; the caller says
   * which family it is reading, so "m" in a depth column is length and "m"
   * in a time column is minutes. */
  var UNIT_DIMENSION_OVERRIDES = {
    'time|m': { canonical: 'min', dimension: 'time', factor: 1.0, offset: 0.0 },
    'time|min': { canonical: 'min', dimension: 'time', factor: 1.0, offset: 0.0 },
    'length|m': { canonical: 'm', dimension: 'length', factor: 1.0, offset: 0.0 },
  };

  /**
   * @param {*} text
   * @param {string|null} [dimension]
   */
  function parseUnit(text, dimension) {
    var normalised = normaliseUnit(text);
    if (!normalised) return null;
    var parts = splitUnitBasis(normalised);
    var body = parts[0], basis = parts[1];
    if (AMBIGUOUS_UNITS[body] || AMBIGUOUS_UNITS[normalised]) return null;
    if (dimension) {
      var override = UNIT_DIMENSION_OVERRIDES[dimension + '|' + body];
      if (override) return Object.assign({}, override, { basis: basis });
    }
    var entry = UNIT_TABLE[body];
    if (!entry) return null;
    if (dimension && entry.dimension !== dimension) return null;
    return Object.assign({}, entry, { basis: basis });
  }

  /** A basis stated on one side only is accepted - a laboratory writing plain
   * "mg/L" for hardness against a "mg/L as CaCO3" guideline means the same
   * thing. Two *different* stated bases are refused.
   * @param {Rec|null|undefined} a what parseUnit returns
   * @param {Rec|null|undefined} b
   * @returns {boolean}
   */
  function unitsComparable(a, b) {
    if (!a || !b) return false;
    if (a.dimension !== b.dimension) return false;
    if (a.basis && b.basis && a.basis !== b.basis) return false;
    return true;
  }

  /** null means "do not use this number against that limit". It never means
   * zero and must never be treated as a pass.
   * @param {number|string} value
   * @param {*} fromUnit
   * @param {*} toUnit
   * @param {string|null} [dimension]
   * @returns {number|null}
   */
  function convertUnit(value, fromUnit, toUnit, dimension) {
    var source = parseUnit(fromUnit, dimension);
    var target = parseUnit(toUnit, dimension);
    if (!unitsComparable(source, target)) return null;
    var base = Number(value) * source.factor + source.offset;
    return (base - target.offset) / target.factor;
  }

  /**
   * @param {*} text
   * @param {string|null} [dimension]
   * @returns {string}
   */
  function canonicalUnit(text, dimension) {
    var unit = parseUnit(text, dimension);
    return unit ? unit.canonical
      : String(text === null || text === undefined ? '' : text).trim();
  }

  /* A unit written on a field sheet appears in brackets: "Time (min)",
   * "Discharge per step (m3/h)". Only bracketed text counts as a declared
   * unit, so an ordinary word in a label is never mistaken for one. */
  var BRACKETED_UNIT_RE = /[(\[]([^)\]]{1,20})[)\]]/g;
  var UNIT_NUMBER_RE = /[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?/;

  var RANGE_IN_LABEL_RE = /\d\s*-\s*\d/;

  /* Every unit a field sheet writes is short, or carries a solidus, or
   * carries a digit: "min", "hrs", "L/s", "m3/h". A longer bare word
   * describes the column - "Time (elapsed)", "(recovery)" - and treating one
   * as an unreadable unit threw away every reading in that column. */
  function isUnitShaped(text) {
    var normalised = normaliseUnit(text);
    if (!normalised || !/[a-z]/.test(normalised)) return false;
    if (RANGE_IN_LABEL_RE.test(normalised) || normalised.indexOf(':') >= 0) {
      return false;
    }
    return normalised.indexOf('/') >= 0 || /\d/.test(normalised) ||
      normalised.length <= 5;
  }

  /**
   * @param {*} text
   * @param {string|null} [dimension]
   */
  function unitFromLabel(text, dimension) {
    var raw = String(text === null || text === undefined ? '' : text);
    var firstWritten = '';
    var re = new RegExp(BRACKETED_UNIT_RE.source, 'g');
    var match;
    while ((match = re.exec(raw)) !== null) {
      var candidate = match[1].trim();
      if (!candidate) continue;
      /* "(step or constant)" is prose, not a unit */
      if (candidate.split(/\s+/).length > 2) continue;
      if (new RegExp('^' + UNIT_NUMBER_RE.source + '$').test(candidate)) continue;
      var unit = parseUnit(candidate, dimension);
      if (unit) return { written: candidate, unit: unit };
      if (!firstWritten && isUnitShaped(candidate)) firstWritten = candidate;
    }
    return { written: firstWritten, unit: null };
  }

  /* A unit beside a number is a short token: "L/s", "m3/h", "min". Anything
   * longer, or with a space inside, or with no letter in it, is a field
   * annotation - "5 (pump off)", "12 pump stopped", "5*" - and reading one as
   * a unit refused the reading. */
  var CELL_UNIT_RE = /^[a-z0-9/\u00b3\u00b2^-]{1,12}$/;

  function unitInCell(cell) {
    if (cell === null || cell === undefined || typeof cell === 'number') return '';
    var text = String(cell).trim().replace(/,/g, '');
    var match = UNIT_NUMBER_RE.exec(text);
    if (!match) return '';
    var tail = (text.slice(0, match.index) + ' ' +
      text.slice(match.index + match[0].length)).trim();
    tail = tail.replace(/^[()[\]:=\s]+|[()[\]:=\s]+$/g, '');
    if (!tail) return '';
    var normalised = normaliseUnit(tail);
    if (!normalised || !CELL_UNIT_RE.test(normalised)) return '';
    if (!/[a-z]/.test(normalised)) return '';
    return tail;
  }

  /** Read a value off a sheet and put it in the canonical unit. The unit is
   * taken from the cell's own text first - a crew that types "0.81 L/s" into
   * a column headed m3/h means L/s - then from each hint in turn. Status is
   * "absent" | "ok" | "converted" | "assumed" | "unknown" (and "clock" for a
   * time written as one); on "unknown" the value is null and the caller must
   * refuse it rather than default. A time is read by readTime, so a clock is
   * a clock wherever it is read: "2:00" under "Time (hh:mm)" was 2 minutes.
   * @param {*} cell
   * @param {Array<*>|null} hints the labels the unit may be written in
   * @param {string} dimension
   */
  function readQuantity(cell, hints, dimension) {
    if (dimension === 'time') return readTime(cell, hints).quantity;
    return readNumber(cell, hints, dimension);
  }

  /* readQuantity for a cell that is a number, with any unit (units.py
   * _read_number) */
  function readNumber(cell, hints, dimension) {
    var canonical = CANONICAL_UNITS[dimension];
    var raw = parseNumber(cell);
    if (raw === null || raw === undefined) {
      return { value: null, raw_value: null, unit_text: '', status: 'absent',
        dimension: dimension };
    }
    function resolve(written) {
      var unit = parseUnit(written, dimension);
      if (!unit) {
        return { value: null, raw_value: raw, unit_text: written,
          status: 'unknown', dimension: dimension };
      }
      return {
        value: convertUnit(/** @type {number} */ (raw), written, canonical, dimension),
        raw_value: raw, unit_text: written,
        status: unit.canonical === canonical ? 'ok' : 'converted',
        dimension: dimension,
      };
    }
    var inCell = unitInCell(cell);
    if (inCell) return resolve(inCell);
    var list = hints || [];
    for (var i = 0; i < list.length; i++) {
      var found = unitFromLabel(list[i], dimension);
      if (!found.written) continue;
      return resolve(found.written);
    }
    return { value: Number(raw), raw_value: raw, unit_text: '',
      status: 'assumed', dimension: dimension };
  }

  /* units.py read_clock: an elapsed time typed as a clock, "1:30",
   * "01:30:00", "1:30:00.5". A cell Excel formats as a time reaches this
   * reader as that text (support.js) and the Python one as a time, and the
   * first number of it was read as the minutes: 01:30 became minute 1 and
   * 00:05 minute 0. */
  var CLOCK_RE = /^\s*([0-9]{1,3}):([0-5][0-9])(?::([0-5][0-9](?:\.[0-9]+)?))?\s*$/;
  /* Text that starts as a clock and is not one - "1:60", "1:5", "1:30 pm",
   * "10:00 (approx)", "1: 30" - or that writes hours and minutes as words -
   * "1h 30m", "1 hr 30 min". Each was read for its first number, so 1:30 pm
   * and 1h 30m were both minute 1; they are refused instead (units.py
   * _NOT_A_CLOCK_RE). */
  var NOT_A_CLOCK_RE = new RegExp('^\\s*[-+]?[0-9]+(?:[.,][0-9]+)?\\s*' +
    '(?::\\s*[0-9]|(?:hours?|hrs?|h|minutes?|mins?|m)\\.?\\s*[0-9])', 'i');
  /* A duration of a day or more, in a cell formatted h:mm, reaches here as a
   * Date on Excel's serial calendar: up to its phantom 29 February 1900 the
   * serial is the days since 31 December 1899. Any other date is a date. */
  var SERIAL_ZERO_MS = Date.UTC(1899, 11, 31);
  var SERIAL_PHANTOM_MS = Date.UTC(1900, 1, 28);

  /** How a two-part clock in a column is read: 'hm' or 'ms'. A header that
   * names its clock - "Time (mm:ss)", "Time (min:sec)" - says "5:30" is five
   * and a half minutes; otherwise it is read as Excel reads "5:30" typed into
   * a cell, five hours and a half (units.py clock_format).
   * @param {Array<*>|null} hints the labels the clock may be named in
   * @returns {string}
   */
  function clockFormat(hints) {
    var list = hints || [];
    for (var i = 0; i < list.length; i++) {
      var re = new RegExp(BRACKETED_UNIT_RE.source, 'g');
      var raw = String(list[i] === null || list[i] === undefined ? '' : list[i]);
      var match;
      while ((match = re.exec(raw)) !== null) {
        var parts = match[1].split(':').map(function (p) { return p.trim().toLowerCase(); });
        if (parts.length >= 2 && ['h', 'm'].indexOf(parts[0].charAt(0)) >= 0 &&
            ['m', 's'].indexOf(parts[1].charAt(0)) >= 0) {
          return parts[0].charAt(0) === 'm' ? 'ms' : 'hm';
        }
      }
    }
    return 'hm';
  }

  /* "01:30:00": a time cell as support.js writes one */
  function clockText(seconds) {
    var ms = Math.round(seconds * 1000);
    var two = function (/** @type {number} */ n) { return String(n).padStart(2, '0'); };
    var text = two(Math.floor(ms / 3600000)) + ':' + two(Math.floor(ms / 60000) % 60) +
      ':' + two(Math.floor(ms / 1000) % 60);
    return ms % 1000 ? text + '.' + String((ms % 1000) * 1000).padStart(6, '0') : text;
  }

  /** {minutes, written} for an elapsed time written as a clock, or null for
   * a cell that is not one (units.py read_clock).
   * @param {*} cell
   * @param {string} [format] what clockFormat says of the column
   * @returns {{minutes: number, written: string}|null}
   */
  function readClock(cell, format) {
    if (cell instanceof Date) {
      var ms = cell.getTime();
      if (!(ms > SERIAL_ZERO_MS && ms < SERIAL_PHANTOM_MS)) return null;
      var seconds = (ms - SERIAL_ZERO_MS) / 1000;
      return { minutes: seconds / 60, written: clockText(seconds) };
    }
    if (typeof cell !== 'string') return null;
    var m = CLOCK_RE.exec(cell);
    if (!m) return null;
    var first = parseInt(m[1], 10), second = parseInt(m[2], 10);
    var minutes;
    if (m[3] !== undefined) minutes = first * 60 + second + parseFloat(m[3]) / 60;
    else if (format === 'ms') minutes = first + second / 60;
    else minutes = first * 60 + second;
    return { minutes: minutes, written: cleanText(cell) };
  }

  /** A date, or a date and time of day: never an elapsed time.
   * @param {*} cell
   * @returns {boolean}
   */
  function isDateCell(cell) {
    return cell instanceof Date && readClock(cell) === null;
  }

  /** {quantity, clock}: an elapsed time in minutes, and the clock it was
   * written as ('' when none). A clock is read as one, status 'clock'; a date
   * is refused, status 'unknown', since a reading's time since the pump
   * started cannot be told from the day it was taken, and so is text that
   * starts as a clock and is not one ("1:60", "1:30 pm") or writes hours and
   * minutes as words ("1h 30m"); anything else is read as a number in the
   * time dimension, its unit taken as readQuantity takes one (units.py
   * read_time).
   * @param {*} cell
   * @param {Array<*>|null} hints the labels the unit may be written in
   * @returns {{quantity: Rec, clock: string}}
   */
  function readTime(cell, hints) {
    var clock = readClock(cell, clockFormat(hints));
    if (clock) {
      return { quantity: { value: clock.minutes, raw_value: clock.minutes, unit_text: '',
        status: 'clock', dimension: 'time' }, clock: clock.written };
    }
    /* an Excel TRUE is no time either: Python read it as minute 1 and this
     * reader left it out without a word */
    if (typeof cell === 'boolean') {
      return { quantity: { value: null, raw_value: null, unit_text: cell ? 'TRUE' : 'FALSE',
        status: 'unknown', dimension: 'time' }, clock: '' };
    }
    if (isDateCell(cell) || (typeof cell === 'string' && NOT_A_CLOCK_RE.test(cell))) {
      return { quantity: { value: null, raw_value: null, unit_text: cleanText(cell),
        status: 'unknown', dimension: 'time' }, clock: '' };
    }
    return { quantity: readNumber(cell, hints, 'time'), clock: '' };
  }

  Object.assign(C, {
    normaliseUnit: normaliseUnit, parseUnit: parseUnit,
    convertUnit: convertUnit, unitsComparable: unitsComparable,
    canonicalUnit: canonicalUnit, unitFromLabel: unitFromLabel,
    readQuantity: readQuantity, CANONICAL_UNITS: CANONICAL_UNITS,
    clockFormat: clockFormat, readClock: readClock, isDateCell: isDateCell,
    readTime: readTime,
  });

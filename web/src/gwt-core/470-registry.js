
  /* ===================================================================
   * The asset registry - a port of groundwater/registry.py
   *
   * A drilling project ends; the borehole does not. This is the other half:
   * a stable identifier, an append-only event stream, and what that stream
   * says is true today. Field updates are recorded at the wellhead with no
   * signal, so events are identified by their content and merging two
   * phones is a set union that needs no server to arbitrate it. Nothing is
   * assumed working: an asset with no events is unknown, not functional.
   * =================================================================== */

  var CROCKFORD = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';
  var CROCKFORD_FOLD = { I: '1', L: '1', O: '0', U: 'V' };
  var CHECK_ALPHABET = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ';
  var POSITION_STEP_M = 10;

  var DISTRICT_CODES = {
    'western area urban': 'WAU', 'western area rural': 'WAR', 'port loko': 'PL',
    kambia: 'KAM', karene: 'KAR', bombali: 'BOM', falaba: 'FAL',
    koinadugu: 'KOI', tonkolili: 'TON', kono: 'KON', kenema: 'KEN',
    kailahun: 'KAI', bo: 'BO', bonthe: 'BON', moyamba: 'MOY', pujehun: 'PUJ'
  };
  var UNKNOWN_DISTRICT = 'XX';
  var ASSET_ID_RE = /^SL-([A-Z]{2,4})-([0-9A-Z]{7})-([0-9A-Z])$/;

  /* ISO 7064's hybrid system for M = 36: the running sum is reduced modulo M
   * (36, with 0 written as 36) and doubled modulo M + 1 (37). */
  var CHECK_M = 36;

  function checkWith(body, modulus) {
    var product = CHECK_M;
    var text = String(body || '').toUpperCase();
    for (var i = 0; i < text.length; i++) {
      var value = CHECK_ALPHABET.indexOf(text.charAt(i));
      if (value < 0) continue;             /* separators carry no value */
      var total = (product % (CHECK_M + 1)) + value;
      product = 2 * ((total % modulus) || modulus);
    }
    return CHECK_ALPHABET.charAt((CHECK_M + 1 - product % (CHECK_M + 1)) % CHECK_M);
  }

  /** ISO 7064 MOD 37,36, the running sum reduced modulo 36 and doubled
   * modulo 37 as the standard's hybrid system has it. It used to be reduced
   * modulo 37, which left 37 final states for 36 check characters, so two
   * of them shared one: about one single mistyped character in 680 still
   * validated, and the identifier did not match the standard's own worked
   * examples. Done as the standard has it, every single wrong character is
   * caught; most transpositions of two adjacent characters are too, but not
   * all: of the 45,360 ways two different characters can meet in one of the
   * calculation's 36 states, 72 leave the state unchanged (one in 630),
   * which is the hybrid system's own limit rather than a slip here.
   * @param {*} body
   * @returns {string}
   */
  function checkCharacter(body) {
    return checkWith(body, CHECK_M);
  }

  /** The check character identifiers were minted with before the
   * correction: reduced modulo 37 rather than 36. Kept so an identifier
   * already painted on a plate, or already holding a history in a project
   * file, still reads; never used to mint.
   * @param {*} body
   * @returns {string}
   */
  function legacyCheckCharacter(body) {
    return checkWith(body, CHECK_M + 1);
  }

  function positionCode(easting, northing, zone) {
    /* Python's round(): two teams at one wellhead have to mint the same
     * identifier, and an easting on an exact five-metre tie is where
     * Math.round and round() part company. */
    var east = pyRound(Number(easting) / POSITION_STEP_M, 0);
    var north = pyRound(Number(northing) / POSITION_STEP_M, 0);
    if (!(east >= 0 && east < 131072) || !(north >= 0 && north < 131072)) {
      throw new Error('(' + easting + ', ' + northing + ') is not a position ' +
        'inside Sierra Leone; an identifier minted from it would not be findable');
    }
    /* 35 bits - zone flag, easting, northing, each to the nearest 10 m - cut
     * into seven groups of five. Split into a top character and a 30-bit
     * remainder because JavaScript's bitwise operators are 32-bit and would
     * silently wrap the whole value. */
    var top = ((Number(zone) === 29 ? 1 : 0) << 4) | (east >> 13);
    var rest = (east & 0x1FFF) * 131072 + north;
    var chars = CROCKFORD.charAt(top & 31);
    for (var shift = 25; shift >= 0; shift -= 5) {
      chars += CROCKFORD.charAt(Math.floor(rest / Math.pow(2, shift)) & 31);
    }
    return chars;
  }

  function districtCode(district) {
    var key = String(district || '').trim().toLowerCase();
    return own(DISTRICT_CODES, key) ? DISTRICT_CODES[key] : UNKNOWN_DISTRICT;
  }

  function formatAssetId(district, position) {
    var body = 'SL-' + district + '-' + position;
    return body + '-' + checkCharacter(body);
  }

  /**
   * @param {Rec|null} site
   * @returns {string}
   */
  function mintAssetId(site) {
    var s = site || {};
    if (s.easting === null || s.easting === undefined ||
        s.northing === null || s.northing === undefined) {
      throw new Error('a borehole with no recorded position cannot be given ' +
        'an identifier: there would be nothing to find it by');
    }
    /* Degrees typed into the two boxes are not a position in metres. The
     * readiness gate read them as degrees and passed the plate, while this
     * refused them, so a plate was certified for an identifier nobody could
     * mint. Both engines now refuse them, in the same words. */
    var degrees = degreesInUtmBoxes(s.easting, s.northing);
    if (degrees) throw new Error(degrees);
    var zone = s.utm_zone || inferZoneForSierraLeone(Number(s.easting));
    return formatAssetId(districtCode(s.district),
      positionCode(s.easting, s.northing, zone));
  }

  /**
   * @param {*} text
   * @returns {string|null}
   */
  function parseAssetId(text) {
    var raw = String(text === null || text === undefined ? '' : text)
      .replace(/[\s_]+/g, '').toUpperCase().replace(/–/g, '-');
    if (!raw) return null;
    if (raw.indexOf('SL-') !== 0) raw = 'SL-' + raw;
    var parts = raw.split('-');
    if (parts.length !== 4) return null;
    var district = parts[1], code = parts[2], given = parts[3];
    code = code.split('').map(function (ch) {
      return own(CROCKFORD_FOLD, ch) ? CROCKFORD_FOLD[ch] : ch;
    }).join('');
    var candidate = 'SL-' + district + '-' + code + '-' + given;
    if (!ASSET_ID_RE.test(candidate)) return null;
    var body = 'SL-' + district + '-' + code;
    /* An identifier minted before the check character followed ISO 7064
     * exactly is still the identifier on its plate and in its project file,
     * so it is read as it is rather than refused or renamed:
     * validateAssetId says that it carries the older character. */
    if (given !== checkCharacter(body) && given !== legacyCheckCharacter(body)) return null;
    return candidate;
  }

  /** Whether an identifier checks only against the legacy check character.
   * @param {*} assetId
   * @returns {boolean}
   */
  function isLegacyAssetId(assetId) {
    var parsed = parseAssetId(assetId);
    if (!parsed) return false;
    var cut = parsed.lastIndexOf('-');
    return checkCharacter(parsed.slice(0, cut)) !== parsed.slice(cut + 1);
  }

  /** {ok, reason, assetId}. An identifier carrying the legacy check character
   * is accepted, and its reason is the note saying so rather than ''.
   * @param {*} text */
  function validateAssetId(text) {
    var raw = String(text === null || text === undefined ? '' : text).trim();
    if (!raw) return { ok: false, reason: 'No identifier was entered.' };
    var parsed = parseAssetId(raw);
    if (parsed) {
      if (isLegacyAssetId(parsed)) {
        /* read, and said: while the older character is read, about one
         * single mistyped character in 36 matches it, so the person typing
         * is told to compare the identifier with the plate */
        return { ok: true, assetId: parsed, legacy: true,
          reason: phrase('registry.legacy_check_character', { asset_id: parsed,
            expected: checkCharacter(parsed.slice(0, parsed.lastIndexOf('-'))) }) };
      }
      return { ok: true, reason: '', assetId: parsed, legacy: false };
    }
    var tidy = raw.replace(/[\s_]+/g, '').toUpperCase();
    if (tidy.indexOf('SL-') !== 0) tidy = 'SL-' + tidy;
    var parts = tidy.split('-');
    if (parts.length !== 4) {
      return { ok: false, reason: 'An identifier looks like SL-WAR-8T4KQ2A-7: ' +
        'country, district, position, check character.' };
    }
    var code = parts[2].split('').map(function (ch) {
      return own(CROCKFORD_FOLD, ch) ? CROCKFORD_FOLD[ch] : ch;
    }).join('');
    if (!/^[0-9A-Z]{7}$/.test(code)) {
      return { ok: false, reason: 'The position part should be seven letters or digits.' };
    }
    var expected = checkCharacter('SL-' + parts[1] + '-' + code);
    return { ok: false, reason: 'The check character does not match: this ' +
      'identifier should end in ' + expected + ', not ' + parts[3] +
      '. Something in it has been mistyped.' };
  }

  /* kind -> [label, what it establishes about function, is it a service visit].
   * A routine inspection is the area mechanic's visit to the pump and the
   * rising main (PLAN.md step 7.3); an inspection is the sanitary inspection,
   * as it always was. A repair is not counted as a routine inspection. The
   * last three are what somebody at the pump reports from its plate or by
   * SMS (PLAN.md step 7.1; a report that it is broken is a failure): working
   * says so, and slow or a water quality complaint says something is the
   * matter without saying whether water comes, so establishes nothing. */
  var EVENT_KINDS = {
    commissioned: ['Commissioned', 'functional', false],
    inspection: ['Sanitary inspection', null, true],
    routine_inspection: ['Routine inspection', null, true],
    water_sample: ['Water sampled', null, false],
    repair: ['Repair', 'functional', true],
    failure: ['Failure', 'non_functional', true],
    restored: ['Returned to service', 'functional', true],
    decommissioned: ['Decommissioned', 'decommissioned', false],
    note: ['Note', null, false],
    reported_working: ['Reported working', 'functional', false],
    reported_slow: ['Reported slow', null, false],
    quality_complaint: ['Water quality complaint', null, false]
  };

  /* The order events recorded on one day are read in (registry.py
   * SAME_DAY_ORDER). Sorting them by kind name put "decommissioned" before
   * "failure", "repair" and "restored", so a hole recorded as collapsed and
   * decommissioned on one visit read "Not working" and stayed due an
   * inspection, and a pump pulled for reuse on the decommissioning day read
   * "Working". This order is a choice, stated: on a day the borehole is
   * commissioned first, then visited, found broken, mended, and only then
   * decommissioned. Kinds of the same rank keep their name order. */
  var SAME_DAY_ORDER = {
    commissioned: 0, inspection: 1, water_sample: 1, note: 1,
    failure: 2, repair: 3, restored: 3, decommissioned: 4
  };

  function dayRank(kind) {
    return own(SAME_DAY_ORDER, kind) ? SAME_DAY_ORDER[kind] : 1;
  }

  /* when, then the day's order, then kind, then id: merge_events' key */
  function eventOrder(a, b) {
    var aw = a.when || '9999', bw = b.when || '9999';
    if (aw !== bw) return aw < bw ? -1 : 1;
    if (dayRank(a.kind) !== dayRank(b.kind)) return dayRank(a.kind) - dayRank(b.kind);
    if (a.kind !== b.kind) return a.kind < b.kind ? -1 : 1;
    return a.event_id < b.event_id ? -1 : (a.event_id > b.event_id ? 1 : 0);
  }

  var FUNCTION_LABELS = {
    functional: 'Working', non_functional: 'Not working',
    decommissioned: 'Decommissioned', unknown: 'Not known'
  };

  var FUNCTION_COLORS = {
    functional: '#2E7D5B', non_functional: '#B23A2E',
    decommissioned: '#6B7785', unknown: '#6B7785'
  };

  /* FNV-1a, kept to 32 bits with the same multiply-and-mask the Python side
   * uses, so both engines derive the same event identifier. */
  function hash32(text) {
    var value = 0x811C9DC5;
    for (var i = 0; i < text.length; i++) {
      value = (value ^ (text.charCodeAt(i) & 0xFF)) >>> 0;
      /* Math.imul, not a plain multiply: 2^32 times the FNV prime is well
       * past 2^53, so the ordinary product loses low bits and the two
       * engines would derive different event identifiers. */
      value = Math.imul(value, 0x01000193) >>> 0;
    }
    return value >>> 0;
  }

  /* What trimField takes off the ends of a registry field, as a regular
   * expression's character class: every character either engine's own trim
   * would take, written out. String.trim and Python's str.strip disagree on
   * a handful - Python strips U+001C to U+001F and U+0085, JavaScript the
   * byte order mark U+FEFF - so the same stored answers scored in one
   * engine and not the other. The union, rather than the ASCII blanks the
   * field kit's codes are trimmed of, because event identifiers were
   * already derived from trimmed notes: the union changes no identifier the
   * two engines agreed on. _TRIMMED in groundwater/registry.py is the twin. */
  var TRIMMED = '\\t\\n\\v\\f\\r\\x1c-\\x1f \\x85\\xa0\\u1680\\u2000-\\u200a' +
    '\\u2028\\u2029\\u202f\\u205f\\u3000\\ufeff';
  var TRIM_RE = new RegExp('^[' + TRIMMED + ']+|[' + TRIMMED + ']+$', 'g');

  /** A field with the blanks at its ends taken off, as both engines take
   * them: the twin of trim_field in groundwater/registry.py.
   * @param {*} text
   * @returns {string}
   */
  function trimField(text) {
    return String(text === null || text === undefined ? '' : text).replace(TRIM_RE, '');
  }

  /** A sanitary inspection's form and answers (PLAN.md step 7.5) are part of
   * its content; an event without them hashes as it always did.
   * @param {string} assetId
   * @param {string} when an ISO day
   * @param {string} kind
   * @param {*} [note]
   * @param {*} [by]
   * @param {*} [form]
   * @param {*} [answers]
   * @returns {string}
   */
  function eventId(assetId, when, kind, note, by, form, answers) {
    var content = assetId + '|' + when + '|' + kind + '|' +
      trimField(note || '') + '|' + trimField(by || '');
    if (form || answers) content += '|' + (form || '') + '|' + (answers || '');
    var digest = hash32(content);
    var tail = [15, 10, 5, 0].map(function (shift) {
      return CROCKFORD.charAt((digest >>> shift) & 31);
    }).join('');
    return when + '/' + kind + '/' + tail;
  }

  /**
   * @param {string} kind
   * @returns {string}
   */
  function eventLabel(kind) {
    return own(EVENT_KINDS, kind) ? EVENT_KINDS[kind][0] : 'Other';
  }

  var ISO_DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

  /** Days since the epoch, or null when the date cannot be read. Kept as a
   * day number rather than a Date so arithmetic never meets a time zone.
   * The same rule as iso_date in groundwater/registry.py: YYYY-MM-DD and
   * nothing else, in years 1 to 9999, as Python's date has them.
   * @param {*} text
   * @returns {number|null}
   */
  function isoDay(text) {
    var match = ISO_DATE_RE.exec(trimField(text));
    if (!match) return null;
    var year = Number(match[1]), month = Number(match[2]), day = Number(match[3]);
    if (year < 1 || month < 1 || month > 12 || day < 1 ||
        day > daysInMonth(year, month)) return null;
    /* setUTCFullYear, not Date.UTC, which reads years 0 to 99 as 1900 to
     * 1999 and so put a mistyped 0024 eighteen centuries from Python's */
    var at = new Date(0);
    at.setUTCFullYear(year, month - 1, day);
    return Math.floor(at.getTime() / 86400000);
  }

  function isLeap(year) {
    return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  }

  function daysInMonth(year, month) {
    return [31, isLeap(year) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1];
  }

  /**
   * @param {number|null} [day]
   * @returns {string|null}
   */
  function dayToIso(day) {
    if (day === null || day === undefined) return null;
    var d = new Date(day * 86400000);
    return d.toISOString().slice(0, 10);
  }

  /** Clamped rather than rolled over: six months from 31 August is 28
   * February, not 3 March, and a due date that drifts forward is missed.
   * Null past the year 9999, the last a date can hold in either engine.
   * @param {string} iso
   * @param {number} months
   * @returns {string|null}
   */
  function addMonths(iso, months) {
    var match = ISO_DATE_RE.exec(iso);
    if (!match) return null;
    var year = Number(match[1]), month = Number(match[2]) - 1 + months;
    var day = Number(match[3]);
    year += Math.floor(month / 12);
    month = ((month % 12) + 12) % 12 + 1;
    if (year > 9999) return null;
    day = Math.min(day, daysInMonth(year, month));
    /* the year written in four digits, as Python's isoformat writes it, so
     * a due date counted from a day before the year 1000 still reads */
    var y = String(year);
    while (y.length < 4) y = '0' + y;
    return y + '-' + pad2(month) + '-' + pad2(day);
  }

  function pad2(n) { return (n < 10 ? '0' : '') + n; }

  /** A form's answers as stored: Y, N or - for each question, in order. Y
   * and N are read in either case; anything else, a blank included, is a
   * question not answered, because an answer nobody can read is not a no.
   * Read by code point, as Python reads a string, and trimmed as trimField
   * trims.
   * @param {*} raw
   * @returns {string}
   */
  function cleanAnswers(raw) {
    return Array.from(trimField(raw || '')).map(function (c) {
      return c === 'Y' || c === 'y' ? 'Y' : (c === 'N' || c === 'n' ? 'N' : '-');
    }).join('');
  }

  /** A photograph's provenance record as an event keeps it, or null: kept as
   * it stands when it is a mapping whose sha256 is 64 hexadecimal digits in
   * lower case, as both engines write one, and dropped otherwise
   * (registry.clean_photo_provenance).
   * @param {*} raw
   * @returns {Rec|null}
   */
  function cleanPhotoProvenance(raw) {
    if (!isRecord(raw) || typeof raw.sha256 !== 'string' ||
        !/^[0-9a-f]{64}$/.test(raw.sha256)) return null;
    return Object.assign({}, raw);
  }

  function coerceEvent(raw) {
    if (!raw || typeof raw !== 'object') return null;
    var kind = trimField(raw.kind || '');
    if (!own(EVENT_KINDS, kind)) kind = 'note';
    /** @type {Rec} */
    var event = {
      when: trimField(raw.when || ''), kind: kind,
      note: String(raw.note || ''), by: String(raw.by || ''),
      photo: String(raw.photo || '')
    };
    var form = trimField(raw.form || ''), answers = cleanAnswers(raw.answers);
    /* only an event that has them carries them, so a project file with no
     * sanitary inspection in it is written as it was before */
    if (form || answers) {
      event.form = form;
      event.answers = answers;
    }
    /* likewise the photograph's provenance (PLAN.md step 7.1), which is not
     * part of the event's identifier and travels with the photograph */
    var provenance = cleanPhotoProvenance(raw.photo_provenance);
    if (provenance) event.photo_provenance = provenance;
    event.event_id = String(raw.event_id || '');
    return event;
  }

  /**
   * @param {Rec} event
   * @param {string} assetId
   * @returns {Rec}
   */
  function identifiedFor(event, assetId) {
    return Object.assign({}, event, {
      event_id: event.event_id ||
        eventId(assetId, event.when, event.kind, event.note, event.by,
          event.form, event.answers)
    });
  }

  /** The whole offline story: two phones out of touch for a fortnight each
   * hold part of the history, and merging is a union over content-derived
   * identifiers - commutative, idempotent, and needing no clock agreement.
   * @param {string} assetId followed by any number of event lists
   */
  function mergeEvents(assetId) {
    var merged = {}, order = [];
    for (var s = 1; s < arguments.length; s++) {
      (arguments[s] || []).forEach(function (raw) {
        /** @type {Rec|null} */
        var event = coerceEvent(raw);
        if (!event) return;
        event = identifiedFor(event, assetId);
        if (!own(merged, event.event_id)) {
          merged[event.event_id] = event;
          order.push(event.event_id);
        } else if (!merged[event.event_id].photo && event.photo) {
          merged[event.event_id] = event;
        }
      });
    }
    return order.map(function (key) { return merged[key]; }).sort(eventOrder);
  }

  /**
   * @param {Rec|null} asset
   * @returns {[number, number]|null}
   */
  function assetLatLon(asset) {
    if (!asset || asset.easting === null || asset.easting === undefined ||
        asset.northing === null || asset.northing === undefined) return null;
    var zone = asset.utm_zone || inferZoneForSierraLeone(Number(asset.easting));
    var fix;
    try {
      fix = utmToGeographic(Number(asset.easting), Number(asset.northing), Number(zone));
    } catch (err) {
      return null;
    }
    /* a pair, matching the Python tuple, so both engines index it the same */
    return fix ? [fix.lat, fix.lon] : null;
  }

  /**
   * @param {Rec|null} asset
   * @returns {string}
   */
  function assetLabel(asset) {
    var place = (asset && asset.community) || '(unnamed site)';
    return asset && asset.district ? place + ' (' + asset.district + ')' : place;
  }

  /** How often a point is visited (registry.Schedule.from_config): the
   * configuration's service section, and its design rules' interval for a
   * rising main in water whose corrosivity is not known, which is the routine
   * inspection's interval for a record that carries no rising main. These
   * are a programme's choices, not a standard.
   * @param {Config|null} [cfg] a configuration; the defaults when not given
   * @returns {Rec}
   */
  function serviceSchedule(cfg) {
    var c = cfg || defaultConfig();
    return {
      sanitary_inspection_months: c.service.sanitary_inspection_months,
      water_sample_months: c.service.water_sample_months,
      grace_days: c.service.grace_days,
      routine_inspection_months: c.design.aggressive_rising_main_inspection_months
    };
  }

  /* registry._MAX_MONTHS: a hundred years, the longest interval a record may
   * set; a longer one is not an interval anybody meant */
  var MAX_MONTHS = 1200;

  /* a number of months from 1 to 1200, or null: a whole number, as Python
   * reads it too (5.0 is 5, true is not a number) */
  function wholeMonths(value) {
    return typeof value === 'number' && isFinite(value) && value === Math.floor(value) &&
      value >= 1 && value <= MAX_MONTHS ? value : null;
  }

  /* registry.Schedule.__post_init__: an interval no due date can be counted
   * with is refused, so a configuration that set one does not give a due
   * date in one engine and nonsense in the other */
  function checkSchedule(plan) {
    ['sanitary_inspection_months', 'water_sample_months', 'routine_inspection_months']
      .forEach(function (name) {
        if (wholeMonths(plan[name]) === null) {
          throw new Error('schedule: ' + name + ' must be a whole number of months from 1 to ' +
            MAX_MONTHS);
        }
      });
    var grace = plan.grace_days;
    if (!(typeof grace === 'number' && isFinite(grace) && grace === Math.floor(grace) &&
        grace >= 0)) {
      throw new Error('schedule: grace_days must be a whole number of days, 0 or more');
    }
    return plan;
  }

  /* a text field of a record, trimmed, or blank when it is not text */
  function textField(value) {
    return typeof value === 'string' ? trimField(value) : '';
  }

  /** The rising main a record carries, as both engines keep it, or null
   * (registry.clean_rising_main): the interval a whole number of months from
   * 1 to 1200, or no rising main at all; the material trimmed; the chemistry
   * kept only when it is a state the design names.
   * @param {*} raw a design's rising main or a stored record's
   * @returns {Rec|null}
   */
  function cleanRisingMain(raw) {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
    var months = wholeMonths(raw.inspection_months);
    if (months === null) return null;
    var chemistry = textField(raw.chemistry);
    return {
      material: textField(raw.material), inspection_months: months,
      chemistry: own(phraseTable('rounds.water'), chemistry) ? chemistry : ''
    };
  }

  /** A copy of the record carrying the rising main of its project's design;
   * the record as it is when the design gives none.
   * @param {Rec} asset
   * @param {*} risingMain a design's rising main
   * @returns {Rec}
   */
  function assetWithRisingMain(asset, risingMain) {
    var clean = cleanRisingMain(risingMain);
    if (!clean) return asset;
    return Object.assign({}, asset, { rising_main: clean });
  }

  function dueItem(key, title, last, commissioned, months, graceDays, today, why, basis) {
    var anchor = last || commissioned;
    if (!anchor) {
      return { key: key, title: title, due_on: null, state: 'unknown',
        detail: 'No ' + title.toLowerCase() + ' has been recorded, and there ' +
          'is no commissioning date to count from. ' + why,
        months: months, basis: basis };
    }
    var dueOn = addMonths(anchor, months);
    if (dueOn === null) {
      return { key: key, title: title, due_on: null, state: 'scheduled',
        detail: phrase('rounds.beyond', { title: title.toLowerCase() }),
        months: months, basis: basis };
    }
    /* both are days that read: dueOn is counted from a recorded day that
     * did, and today is the clock's own date unless a caller passes one */
    var dueDay = /** @type {number} */ (isoDay(dueOn)),
      todayDay = /** @type {number} */ (isoDay(today));
    var late = todayDay - dueDay;
    if (late > graceDays) {
      var never = last ? '' : 'has never been done; it ';
      return { key: key, title: title, due_on: dueOn, state: 'overdue',
        detail: title + ' ' + never + 'has been due since ' + dueOn + ', ' +
          late + ' days ago. ' + why,
        months: months, basis: basis };
    }
    if (late > 0) {
      return { key: key, title: title, due_on: dueOn, state: 'due',
        detail: title + ' fell due on ' + dueOn + '.', months: months, basis: basis };
    }
    return { key: key, title: title, due_on: dueOn, state: 'scheduled',
      detail: 'Next ' + title.toLowerCase() + ' due ' + dueOn + '.',
      months: months, basis: basis };
  }

  /* registry._routine_interval: the routine inspection's interval and where
   * it comes from - the rising main the record carries from the design, else
   * the schedule's interval for a record that carries none */
  function routineInterval(asset, plan) {
    var rising = cleanRisingMain(asset.rising_main);
    if (!rising) {
      return [plan.routine_inspection_months, phrase('rounds.basis_default',
        { months: plan.routine_inspection_months })];
    }
    var months = rising.inspection_months;
    if (rising.material && rising.chemistry) {
      return [months, phrase('rounds.basis_design', { months: months,
        material: rising.material, water: phraseTable('rounds.water')[rising.chemistry] })];
    }
    return [months, phrase('rounds.basis_record', { months: months })];
  }

  /**
   * @param {Rec} asset
   * @param {string|null} [today] an ISO day; today when not given
   * @param {Rec|null} [schedule]
   */
  function assetState(asset, today, schedule) {
    var when = today || new Date().toISOString().slice(0, 10);
    var plan = checkSchedule(Object.assign({}, serviceSchedule(), schedule || {}));
    var events = mergeEvents(asset.asset_id, asset.events || []);
    /* the clock's own date unless the caller passes one */
    var todayDay = /** @type {number} */ (isoDay(when));
    var dated = events.filter(function (e) { return isoDay(e.when) !== null; })
      .sort(eventOrder);
    var undated = events.length - dated.length;

    var fn = 'unknown', since = null;
    var detail = 'Nothing has been recorded against this borehole, so whether ' +
      'it is working is not known.';
    var commissioned = null, lastInspection = null, lastSample = null, lastRoutine = null;
    var afterDecommissioning = [];
    dated.forEach(function (event) {
      if (/** @type {number} */ (isoDay(event.when)) > todayDay) return;
      var establishes = EVENT_KINDS[event.kind][1];
      if (establishes && fn === 'decommissioned' && event.kind !== 'commissioned') {
        /* Decommissioning is terminal: a repair or a failure logged after it
         * stays in the history but does not bring the borehole back. Only a
         * new commissioning record does. A second decommissioning record
         * changes nothing, as a second failure report does not. */
        if (establishes !== 'decommissioned') afterDecommissioning.push(event);
      } else if (establishes && establishes !== fn) {
        /* Only a change moves "since". A villager reporting a broken pump
         * again in May, as the plate reports of PLAN.md step 7.1 will,
         * restarted the count from May, so a borehole out since January
         * showed 12 days out of service rather than 143. */
        fn = establishes;
        since = event.when;
        detail = eventLabel(event.kind) + ' recorded on ' + event.when +
          (event.by ? ' by ' + event.by : '');
        afterDecommissioning = [];
      }
      if (event.kind === 'commissioned' && !commissioned) commissioned = event.when;
      if (event.kind === 'inspection') lastInspection = event.when;
      if (event.kind === 'routine_inspection') lastRoutine = event.when;
      if (event.kind === 'water_sample') lastSample = event.when;
    });

    if (fn === 'decommissioned' && afterDecommissioning.length) {
      detail += '. ' + phrase('registry.after_decommissioning', {
        n: afterDecommissioning.length,
        events: andJoin(afterDecommissioning.map(function (e) {
          return phrase('registry.event_on',
            { event: eventLabel(e.kind).toLowerCase(), when: e.when });
        })) });
    }
    var outFor = fn === 'non_functional' && since ? todayDay - /** @type {number} */ (isoDay(since)) : null;
    if (undated && fn === 'unknown') {
      detail = undated + ' record(s) carry a date nobody can read, so nothing ' +
        'can be established from them.';
    }

    var due = [];
    if (fn !== 'decommissioned') {
      due.push(dueItem('inspection', 'Sanitary inspection', lastInspection,
        commissioned, plan.sanitary_inspection_months, plan.grace_days, when,
        'A sanitary inspection is what catches a cracked apron or a latrine ' +
        'dug uphill before the water shows it.',
        phrase('rounds.basis_sanitary', { months: plan.sanitary_inspection_months })));
      var routine = routineInterval(asset, plan);
      due.push(dueItem('routine_inspection', EVENT_KINDS.routine_inspection[0], lastRoutine,
        commissioned, routine[0], plan.grace_days, when, phrase('rounds.routine_why'),
        routine[1]));
      due.push(dueItem('water_sample', 'Water quality sample', lastSample,
        commissioned, plan.water_sample_months, plan.grace_days, when,
        'Water that was safe at handover is not evidence that it is safe now: ' +
        'the aquifer, the headworks and the catchment all change.',
        phrase('rounds.basis_sample', { months: plan.water_sample_months })));
    }
    return {
      function: fn, label: FUNCTION_LABELS[fn], since: since, detail: detail,
      last_inspection: lastInspection, last_sample: lastSample,
      last_routine_inspection: lastRoutine,
      commissioned: commissioned, days_out_of_service: outFor,
      due: due, undated_events: undated,
      overdue: due.filter(function (item) { return item.state === 'overdue'; }),
      is_working: fn === 'functional'
    };
  }

  /* The browser app's address for the report page of one borehole, after
   * the app's own address (PLAN.md steps 1.4 and 7.1): registry.REPORT_ROUTE. */
  var REPORT_ROUTE = '#/report/';

  /* registry._REPORT_URL: https:// in either case, A to Z only, a first
   * character that is not /, ? or #, then printable ASCII with no blank and
   * no # */
  var REPORT_URL_RE =
    /^[Hh][Tt][Tt][Pp][Ss]:\/\/[\x21\x22\x24-\x2e\x30-\x3e\x40-\x7e][\x21\x22\x24-\x7e]*$/;

  /** Why url cannot be the address a plate's symbol links to, or '' when it
   * can or none is set (registry.check_report_url): https, because a browser
   * keeps an app for use with no network only from a secure address, in
   * printable ASCII with no blank and no # part.
   * @param {*} url
   * @returns {string}
   */
  function checkReportUrl(url) {
    var text = trimField(url);
    if (!text) return '';
    if (!REPORT_URL_RE.test(text)) return phrase('fault_reports.url_refused', { url: text });
    return '';
  }

  /** The link a plate's symbol carries to the report page of assetId, or ''
   * when no address is set; an address checkReportUrl refuses is refused.
   * @param {string} assetId
   * @param {*} [reportUrl]
   * @returns {string}
   */
  function reportLink(assetId, reportUrl) {
    var reason = checkReportUrl(reportUrl);
    if (reason) throw new Error(reason);
    var text = trimField(reportUrl);
    return text ? text + REPORT_ROUTE + assetId : '';
  }

  /** What a scan of the plate of assetId begins with: the link to its report
   * page where an address is set, else BOREHOLE and the identifier.
   * @param {string} assetId
   * @param {*} [reportUrl]
   * @returns {string}
   */
  function scanStart(assetId, reportUrl) {
    return reportLink(assetId, reportUrl) || 'BOREHOLE ' + assetId;
  }

  /** With no report address set, plain text, not a link: a technician who
   * scans it sees the identifier, the place and the position with nothing to
   * load, where there is no network. With one set (service.report_url), the
   * link to the browser app's report page for this borehole (PLAN.md step
   * 7.1), which works with no network on a phone that has opened the app.
   * @param {Rec} asset
   * @param {*} [reportUrl]
   * @returns {string}
   */
  function qrPayload(asset, reportUrl) {
    var link = reportLink(asset.asset_id, reportUrl);
    if (link) return link;
    var lines = [scanStart(asset.asset_id), assetLabel(asset)];
    var latlon = assetLatLon(asset);
    if (latlon) {
      lines.push(pyFixed(Math.abs(latlon[0]), 5) + ' ' + (latlon[0] >= 0 ? 'N' : 'S') +
        ', ' + pyFixed(Math.abs(latlon[1]), 5) + ' ' + (latlon[1] >= 0 ? 'E' : 'W'));
    }
    var facts = [];
    if (asset.total_depth_m) facts.push(pyFixed(Number(asset.total_depth_m), 1) + ' m deep');
    if (asset.safe_yield_m3_per_h) {
      facts.push(pyFixed(Number(asset.safe_yield_m3_per_h), 2) + ' m3/h');
    }
    if (asset.pump_type) facts.push(asset.pump_type);
    if (facts.length) lines.push(facts.join(', '));
    return lines.join('\n');
  }

  /**
   * @param {Rec} asset
   * @param {Rec} [state] what assetState returns
   */
  function placardLines(asset, state) {
    var rows = [['Identifier', asset.asset_id],
      ['Community', asset.community || '-']];
    if (asset.district) rows.push(['District', asset.district]);
    var latlon = assetLatLon(asset);
    if (latlon) {
      rows.push(['Position', pyFixed(latlon[0], 5) + ' N, ' +
        pyFixed(Math.abs(latlon[1]), 5) + ' W']);
    }
    if (asset.total_depth_m) {
      rows.push(['Depth', pyFixed(Number(asset.total_depth_m), 1) + ' m']);
    }
    if (asset.safe_yield_m3_per_h) {
      rows.push(['Safe yield', pyFixed(Number(asset.safe_yield_m3_per_h), 2) + ' m3/h']);
    }
    if (asset.pump_type) rows.push(['Pump', asset.pump_type]);
    if (asset.installed_by) rows.push(['Installed by', asset.installed_by]);
    if (state) {
      if (state.commissioned) rows.push(['Commissioned', state.commissioned]);
      rows.push(['Status', state.label]);
    }
    return rows;
  }

  /** @param {*} payload */
  function assetFromDict(payload) {
    if (!payload || typeof payload !== 'object') return null;
    var assetId = parseAssetId(payload.asset_id);
    if (!assetId) return null;
    /** @type {Rec} */
    var asset = {
      asset_id: assetId,
      community: payload.community || '', district: payload.district || '',
      chiefdom: payload.chiefdom || '',
      easting: payload.easting === undefined ? null : payload.easting,
      northing: payload.northing === undefined ? null : payload.northing,
      utm_zone: payload.utm_zone === undefined ? null : payload.utm_zone,
      total_depth_m: payload.total_depth_m === undefined ? null : payload.total_depth_m,
      safe_yield_m3_per_h: payload.safe_yield_m3_per_h === undefined
        ? null : payload.safe_yield_m3_per_h,
      pump_type: payload.pump_type || '', installed_by: payload.installed_by || '',
      events: []
    };
    /* only a record that has them carries them (PLAN.md step 7.3), so a
     * project file with no mechanic named and no rising main is written as
     * it was before */
    var mechanic = textField(payload.area_mechanic);
    if (mechanic) asset.area_mechanic = mechanic;
    var rising = cleanRisingMain(payload.rising_main);
    if (rising) asset.rising_main = rising;
    asset.events = mergeEvents(assetId, payload.events || []);
    /* the issue records of the documents issued about it (PLAN.md step
     * 8.1), likewise only where there are some */
    var documents = cleanIssueRecords(payload.documents);
    if (documents.length) asset.documents = documents;
    return asset;
  }

  /** Nothing is invented here: no commissioning event is written, because a
   * borehole is commissioned by somebody deciding it is, on a day, and that
   * decision is a record with a name on it rather than a side effect of
   * opening a page.
   * @param {Rec} state the project
   */
  function assetFromProject(state) {
    var site = projectSite(state || {});
    if (!site || site.easting === null || site.easting === undefined) return null;
    var assetId;
    try {
      assetId = mintAssetId(site);
    } catch (err) {
      return null;
    }
    var log = state.drilling_log, analysis = state.pump_analysis;
    var recommendation = analysis && analysis.yield_recommendation;
    /** @type {Rec} */
    var asset = {
      asset_id: assetId, community: site.community || '',
      district: site.district || '', chiefdom: site.chiefdom || '',
      easting: site.easting, northing: site.northing,
      utm_zone: site.utm_zone || null,
      total_depth_m: log ? log.total_depth_m : null,
      safe_yield_m3_per_h: recommendation ? recommendation.safe_yield_m3_per_h : null,
      pump_type: '', installed_by: site.contractor || '', events: []
    };
    /* the rising main the design specifies, whose interval the routine
     * inspection is due by (PLAN.md steps 7.2 and 7.3) */
    var design = state.borehole_design;
    var rising = cleanRisingMain(design ? design.rising_main : null);
    if (rising) asset.rising_main = rising;
    /* the documents issued about the borehole from the project, so a record
     * first stored after they were issued holds them (PLAN.md step 8.1) */
    var documents = boreholeRecords(state.issued);
    if (documents.length) asset.documents = documents;
    return asset;
  }

  /**
   * @param {Rec[]|null} assets
   * @param {string|null} [today]
   * @param {Rec|null} [schedule]
   */
  function registryRows(assets, today, schedule) {
    return (assets || []).map(function (asset) {
      var state = assetState(asset, today, schedule);
      return {
        Identifier: asset.asset_id,
        Community: asset.community || '(unnamed)',
        District: asset.district || '',
        Status: state.label,
        Since: state.since || '',
        'Last inspected': state.last_inspection || '',
        'Last sampled': state.last_sample || '',
        Overdue: state.overdue.map(function (i) { return i.title; }).join(', '),
        Events: (asset.events || []).length
      };
    });
  }

  /** n_unknown sits beside the working and broken counts and is never folded
   * into either: a register where most points are unknown looks very like
   * one where most points are working, unless the number is on the page.
   * @param {Rec[]|null} assets
   * @param {string|null} [today]
   * @param {Rec|null} [schedule]
   */
  function registryStats(assets, today, schedule) {
    var list = assets || [];
    var counts = { functional: 0, non_functional: 0, decommissioned: 0, unknown: 0 };
    var overdue = {}, outDays = [];
    list.forEach(function (asset) {
      var state = assetState(asset, today, schedule);
      counts[state.function] += 1;
      if (state.days_out_of_service !== null) outDays.push(state.days_out_of_service);
      state.overdue.forEach(function (item) {
        overdue[item.key] = (own(overdue, item.key) ? overdue[item.key] : 0) + 1;
      });
    });
    var known = counts.functional + counts.non_functional;
    return {
      n_assets: list.length,
      n_functional: counts.functional,
      n_non_functional: counts.non_functional,
      n_decommissioned: counts.decommissioned,
      n_unknown: counts.unknown,
      functionality_rate: known ? counts.functional / known * 100 : null,
      n_overdue_inspection: own(overdue, 'inspection') ? overdue.inspection : 0,
      n_overdue_routine: own(overdue, 'routine_inspection') ? overdue.routine_inspection : 0,
      n_overdue_sample: own(overdue, 'water_sample') ? overdue.water_sample : 0,
      mean_days_out_of_service: outDays.length
        ? outDays.reduce(function (a, b) { return a + b; }, 0) / outDays.length : null
    };
  }

  Object.assign(C, {
    DISTRICT_CODES: DISTRICT_CODES, UNKNOWN_DISTRICT: UNKNOWN_DISTRICT,
    EVENT_KINDS: EVENT_KINDS, FUNCTION_LABELS: FUNCTION_LABELS,
    FUNCTION_COLORS: FUNCTION_COLORS, serviceSchedule: serviceSchedule,
    cleanRisingMain: cleanRisingMain, assetWithRisingMain: assetWithRisingMain,
    checkCharacter: checkCharacter, legacyCheckCharacter: legacyCheckCharacter,
    mintAssetId: mintAssetId, isLegacyAssetId: isLegacyAssetId,
    parseAssetId: parseAssetId, validateAssetId: validateAssetId,
    SAME_DAY_ORDER: SAME_DAY_ORDER,
    eventId: eventId, eventLabel: eventLabel, mergeEvents: mergeEvents,
    cleanAnswers: cleanAnswers, trimField: trimField,
    cleanPhotoProvenance: cleanPhotoProvenance, REPORT_ROUTE: REPORT_ROUTE,
    checkReportUrl: checkReportUrl, reportLink: reportLink, scanStart: scanStart,
    assetState: assetState, assetLatLon: assetLatLon, assetLabel: assetLabel,
    assetFromDict: assetFromDict, assetFromProject: assetFromProject,
    qrPayload: qrPayload, placardLines: placardLines,
    registryRows: registryRows, registryStats: registryStats,
    addMonths: addMonths, isoDay: isoDay, dayToIso: dayToIso
  });

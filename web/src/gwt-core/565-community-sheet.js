
  /* ===================================================== community sheet
   * groundwater/community_sheet.py (PLAN.md step 9.1): the one page the
   * community keeps, as plain data both engines build the same way;
   * gwt-docx.js communitySheet lays it out. How much water the borehole
   * gives, whether it is safe to drink, who to call, how to report a fault
   * and what to keep away from it, in the words of
   * data/text/community_sheet.yaml. Nothing here is new hydrogeology: the
   * amount is the lower end of the yield recommendation rounded down, the
   * answer on safety is the water quality verdict, and the distances are
   * the separation table's. community_sheet.py's notes say why each is
   * what it is. */

  /* the jerrycan water is carried in, in litres */
  var JERRYCAN_L = 20;
  /* lines left to write a name and a number on when no member was entered */
  var BLANK_CONTACTS = 3;
  /* how many committee members the sheet prints: with more, the fullest
   * sheet runs on to a second page, and the builder is told how many were
   * left off */
  var MAX_CONTACTS = 6;
  /* the symbol the square to scan is printed as, as on the plate */
  var SCAN_ECC = 'H';
  /* written out rather than \s, which the two engines read differently */
  var SHEET_SPACE = /[ \t\n\r\f\v]+/g;

  /** Typed text as the sheet prints it (community_sheet.py sheet_text): a
   * long dash as a hyphen with spaces and a short one as a hyphen, each run
   * of spaces one space, the ends trimmed; anything that is not text is no
   * text. Done here, once, so that the two document writers, which tidy text
   * differently, are handed text neither has cause to change.
   * @param {*} value
   * @returns {string} */
  function sheetText(value) {
    if (typeof value !== 'string') return '';
    return trimField(value.replace(/\u2014/g, ' - ').replace(/\u2013/g, '-')
      .replace(SHEET_SPACE, ' '));
  }

  /** A value as a whole number rounded down to two significant figures
   * (community_sheet.py round_down): down, never to nearest, with a small
   * allowance for arithmetic that lands a hair under a whole number.
   * @param {number} value
   * @returns {number} */
  function roundDown(value) {
    var whole = Math.floor(value + 1e-9);
    if (whole < 100) return Math.max(whole, 0);
    var step = Math.pow(10, String(whole).length - 2);
    return Math.floor(whole / step) * step;
  }

  /** The hours of use in a day, where they are a time of day's worth.
   * @param {*} hoursPerDay
   * @returns {number|null} */
  function sheetHours(hoursPerDay) {
    if (typeof hoursPerDay !== 'number') return null;
    return isFinite(hoursPerDay) && hoursPerDay > 0 && hoursPerDay <= 24 ? hoursPerDay : null;
  }

  /**
   * @param {Rec|null|undefined} analysis
   * @param {number|null} hours
   * @param {string[]} notes
   * @returns {Rec}
   */
  function sheetWater(analysis, hours, notes, say) {
    var table = phraseTable('community_sheet.builder_notes');
    /** @type {Rec} */
    var water = {
      heading: say.phrase('community_sheet.water_heading'), state: 'none',
      litres_per_hour: null, jerrycans_per_hour: null, hours_per_day: null,
      litres_per_day: null, jerrycans_per_day: null,
      headline: say.phrase('community_sheet.water_none'), lines: [],
    };
    var rec = analysis ? analysis.yield_recommendation : null;
    if (!rec || rec.safe_yield_m3_per_h === null || rec.safe_yield_m3_per_h === undefined) {
      notes.push(table[analysis ? 'pending' : 'no_test']);
      return water;
    }
    var low = rec.safe_yield_low_m3_per_h;
    var rate = low !== null && low !== undefined ? low : rec.safe_yield_m3_per_h;
    /* the recommendation's own word for a short test, or one inside its
     * casing-storage time, or one no method fitted to standard */
    var indicative = rec.confidence === 'indicative';
    var perHour = roundDown(rate * 1000.0);
    water.state = indicative ? 'first_estimate' : 'measured';
    water.litres_per_hour = perHour;
    water.jerrycans_per_hour = Math.floor(perHour / JERRYCAN_L);
    if (perHour <= 0) {
      water.headline = say.phrase('community_sheet.water_very_little');
    } else if (hours === null) {
      notes.push(table.no_hours);
      if (water.jerrycans_per_hour >= 1) {
        water.headline = say.phrase('community_sheet.water_hour', { cans: water.jerrycans_per_hour });
        /* the litres those jerrycans make, so that the two figures agree by
         * the reader's own arithmetic; a rounding down once more */
        water.lines.push(say.phrase('community_sheet.water_hour_detail',
          { litres: water.jerrycans_per_hour * JERRYCAN_L, can: JERRYCAN_L }));
      } else {
        water.headline = say.phrase('community_sheet.water_litres_hour', { litres: perHour });
      }
    } else {
      var perDay = roundDown(perHour * hours);
      var unit = say.phraseTable('community_sheet.hour_words')[hours === 1 ? 'one' : 'other'];
      water.hours_per_day = hours;
      water.litres_per_day = perDay;
      water.jerrycans_per_day = Math.floor(perDay / JERRYCAN_L);
      if (perDay <= 0) {
        water.headline = say.phrase('community_sheet.water_very_little');
      } else if (water.jerrycans_per_day >= 1) {
        water.headline = say.phrase('community_sheet.water_day', { cans: water.jerrycans_per_day });
        water.lines.push(say.phrase('community_sheet.water_day_detail',
          { litres: water.jerrycans_per_day * JERRYCAN_L, hours: hours, unit: unit,
            can: JERRYCAN_L }));
      } else {
        water.headline = say.phrase('community_sheet.water_litres_day',
          { litres: perDay, hours: hours, unit: unit });
      }
    }
    if (indicative) {
      notes.push(table.first_estimate);
      water.lines.push(say.phrase('community_sheet.water_first_estimate'));
    } else {
      water.lines.push(say.phrase('community_sheet.water_tested'));
    }
    /* nothing to fall short of where the sheet says there is very little */
    if (perHour > 0 && (hours === null || water.litres_per_day > 0)) {
      water.lines.push(say.phrase('community_sheet.water_shortage'));
    }
    return water;
  }

  /**
   * @param {Rec|null|undefined} quality
   * @param {string[]} notes
   * @param {Speaker} say
   * @returns {Rec}
   */
  function sheetQuality(quality, notes, say) {
    var answers = say.phraseTable('community_sheet.quality');
    var state = quality ? quality.verdict_state : null;
    if (!Object.prototype.hasOwnProperty.call(answers, state) || state === 'none') {
      if (!quality) {
        notes.push(phraseTable('community_sheet.builder_notes').no_quality);
        state = 'none';
      } else {
        /* a verdict this sheet has no words for is not told as safe */
        state = 'indeterminate';
      }
    }
    /** @type {string[]} */
    var lines = [];
    if (quality && (state === 'health_fail' || state === 'national_fail')) {
      /* what failed is named for either failure: a national one is, with
       * the bundled standards, coliform bacteria found */
      var found = (state === 'health_fail' ? quality.health_exceedances
        : quality.national_exceedances) || [];
      var names = found.map(function (/** @type {Rec} */ row) { return row.parameter; });
      if (names.length) {
        lines.push(say.phrase('community_sheet.quality_found', { names: names.join(', ') }));
      }
      lines.push(say.phrase('community_sheet.quality_ask'));
    }
    return { heading: say.phrase('community_sheet.quality_heading'), state: state,
      headline: answers[state], lines: lines };
  }

  /**
   * @param {Rec[]|null|undefined} committee
   * @param {string[]} notes
   * @param {Speaker} say
   * @returns {Rec}
   */
  function sheetContacts(committee, notes, say) {
    var columns = say.phraseTable('community_sheet.contacts_columns');
    /** @type {string[][]} */
    var rows = [];
    (committee || []).forEach(function (member) {
      if (!member || typeof member !== 'object') return;
      var role = sheetText(member.role), name = sheetText(member.name);
      var phone = sheetText(member.phone) || sheetText(member.contact);
      if (name || phone) rows.push([role, name, phone]);
    });
    if (rows.length > MAX_CONTACTS) {
      notes.push(phrase('community_sheet.too_many_contacts',
        { shown: MAX_CONTACTS, left: rows.length - MAX_CONTACTS }));
      rows = rows.slice(0, MAX_CONTACTS);
    }
    if (!rows.length) {
      notes.push(phraseTable('community_sheet.builder_notes').no_committee);
      for (var i = 0; i < BLANK_CONTACTS; i += 1) rows.push(['', '', '']);
    }
    var writeIn = say.phraseTable('community_sheet.contacts_write_in');
    Object.keys(writeIn).forEach(function (key) { rows.push([writeIn[key], '', '']); });
    return { heading: say.phrase('community_sheet.contacts_heading'),
      header: [columns.role, columns.name, columns.phone], rows: rows };
  }

  /**
   * @param {string} typed
   * @param {*} reportUrl
   * @param {string[]} notes
   * @param {Speaker} say
   * @returns {Rec}
   */
  function sheetReport(typed, reportUrl, notes, say) {
    var table = phraseTable('community_sheet.builder_notes');
    var lines = [say.phrase('community_sheet.report_tell')];
    var payload = '', caption = '';
    /* the registry's own reading of what was typed: case, spacing and the
     * usual misreadings forgiven, a failing check character not. A number
     * that is not the plate's would send a report to nobody's borehole. */
    var assetId = typed ? (parseAssetId(typed) || '') : '';
    if (!typed) {
      notes.push(table.no_identifier);
    } else if (!assetId) {
      notes.push(table.bad_identifier);
    } else {
      lines.push(say.phrase('community_sheet.report_number', { id: assetId }));
      /* an address the registry refuses stops the sheet, as it stops the
       * plate, rather than being printed */
      payload = reportLink(assetId, reportUrl);
      if (payload) {
        /* a link too long for the symbol stops the sheet here, where both
         * apps show the reason before the button, and not in the writer */
        qrEncode(payload, { ecc: SCAN_ECC });
        lines.push(say.phrase('community_sheet.report_scan'));
        caption = say.phrase('community_sheet.report_caption', { id: assetId });
      } else {
        notes.push(table.no_address);
      }
    }
    return { heading: say.phrase('community_sheet.report_heading'), identifier: assetId,
      lines: lines, payload: payload, caption: caption };
  }

  /** @param {Speaker} say
   * @returns {Rec} */
  function sheetKeepAway(say) {
    var words = say.phraseTable('community_sheet.keep_structures');
    /** @type {Array<[number, string]>} */
    var kept = [];
    loadSeparationDistances().forEach(function (row) {
      if (Object.prototype.hasOwnProperty.call(words, row.structure)) {
        kept.push([row.min_distance_m, words[row.structure]]);
      }
    });
    /* nearest first; the table's own order among things at one distance
     * (Array.prototype.sort is stable, as Python's is) */
    kept.sort(function (a, b) { return a[0] - b[0]; });
    /** @type {Rec[]} */
    var rings = [];
    kept.forEach(function (item) {
      var last = rings[rings.length - 1];
      if (last && last.distance_m === item[0]) {
        last.what.push(item[1]);
      } else {
        rings.push({ distance_m: item[0], what: [item[1]],
          label: say.phrase('community_sheet.keep_metres', { distance: item[0] }) });
      }
    });
    return {
      heading: say.phrase('community_sheet.keep_heading'),
      lines: kept.map(function (item) {
        return say.phrase('community_sheet.keep_line', { what: item[1], distance: item[0] });
      }),
      rings: rings,
      centre: say.phrase('community_sheet.keep_centre'),
      caption: say.phrase('community_sheet.keep_caption'),
    };
  }

  /** Everything the community handover sheet says, as plain data
   * (community_sheet.py community_sheet_content). options.language is the
   * code of the translation the sheet is printed in (C.textLanguages lists
   * those on offer), and nothing for English; options.translations the
   * translations to read it from, the build's own unless given. What the
   * translation has no words for is printed in English and counted for the
   * builder, whose notes are always English.
   *
   * Throws for a report address the registry would not print on a plate,
   * with its reason; for a link too long for the square a phone scans, with
   * the encoder's; and for a language that is not on offer, with every
   * reason it is not.
   * @param {Rec} site the project's header block
   * @param {{analysis?: Rec|null, quality?: Rec|null, committee?: Rec[]|null,
   *   assetId?: string, hoursPerDay?: number|null, example?: boolean,
   *   config?: Config, language?: string,
   *   translations?: Record<string, Rec>}} [options]
   * @returns {Rec} */
  function communitySheetContent(site, options) {
    var opts = options || {};
    var cfg = opts.config || defaultConfig();
    var say = speaker(opts.language, opts.translations);
    /** @type {string[]} */
    var notes = [];
    var place = sheetText(site ? site.community : '');
    var identifier = sheetText(opts.assetId);
    if (opts.example) notes.push(phraseTable('community_sheet.builder_notes').example);
    /** @type {Rec} */
    var content = {
      title: place ? say.phrase('community_sheet.title', { place: place })
        : say.phrase('community_sheet.title_unnamed'),
      /* across the top of a sheet built with a bundled example loaded */
      example: opts.example ? say.phrase('community_sheet.example') : '',
      water: sheetWater(opts.analysis, sheetHours(opts.hoursPerDay), notes, say),
      quality: sheetQuality(opts.quality, notes, say),
      contacts: sheetContacts(opts.committee, notes, say),
      report: sheetReport(identifier, cfg.service.report_url, notes, say),
      keep_away: sheetKeepAway(say),
      language: Object.assign({}, say.language),
      fell_back: say.fellBack.slice(),
    };
    if (say.code) {
      notes.push(phrase('community_sheet.in_language', {
        name: say.language.name, translated_by: say.language.translated_by,
        checked_by: say.language.checked_by }));
      if (say.fellBack.length) {
        notes.push(phrase('community_sheet.not_translated',
          { count: say.fellBack.length, name: say.language.name }));
      }
    } else if (!textLanguages(opts.translations).length) {
      /* with a translation on offer the builder chose English, and is not
       * told that none exists */
      notes.push(phraseTable('community_sheet.builder_notes').english_only);
    }
    content.notes = notes;
    return content;
  }

  Object.assign(C, {
    JERRYCAN_L: JERRYCAN_L, roundDown: roundDown, sheetText: sheetText,
    communitySheetContent: communitySheetContent,
  });

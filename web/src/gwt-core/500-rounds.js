
  /* ===================================================================
   * Service rounds - a port of groundwater/rounds.py (PLAN.md 7.3)
   *
   * The register of many boreholes on a day: which have a visit due (the
   * registry's sanitary inspection, routine inspection and water sample,
   * due, overdue, or due now with nothing to count from), whose round each
   * is on (the area mechanic named on the record, else the one named for its
   * chiefdom, else none), and in what order: a nearest-neighbour walk from
   * the stop due the longest, in straight lines on the ellipsoid to the
   * metre, a tie going to the lower identifier. An order, not an optimal
   * route. The day is an input, never the clock; the words are in
   * text/rounds.yaml.
   * =================================================================== */

  var ROUND_STATES = ['overdue', 'due', 'unknown'];
  /* rounds._MERGED_TEXT and _MERGED_VALUES: taken from the first record of a
   * borehole that has one; a text field is had when it is text that is not
   * blank once trimmed, any other when it is not missing */
  var MERGED_TEXT = ['community', 'district', 'chiefdom', 'pump_type', 'installed_by',
    'area_mechanic'];
  var MERGED_VALUES = ['easting', 'northing', 'utm_zone', 'total_depth_m',
    'safe_yield_m3_per_h', 'rising_main'];

  /* the day the round is drawn up, as a day number; YYYY-MM-DD and nothing
   * else, as iso_date reads it */
  function roundDay(asOf) {
    var day = isoDay(asOf);
    if (day === null) throw new Error('a service round needs the day it is drawn up, as YYYY-MM-DD');
    return day;
  }

  /* A to Z as a to z, nothing else changed, so both engines match exactly
   * the same chiefdom names */
  function foldAscii(text) {
    return text.replace(/[A-Z]/g, function (c) { return c.toLowerCase(); });
  }

  function finiteNumber(value) {
    return typeof value === 'number' && isFinite(value);
  }

  /** The area mechanics by chiefdom, from one line a chiefdom: the
   * chiefdom, a colon and the mechanic's name (rounds.parse_area_mechanics).
   * A line that cannot be read is left out and skipped says why; of two
   * lines naming one chiefdom the first is used.
   * @param {*} text
   * @returns {{entries: Rec[], skipped: string[]}}
   */
  function parseAreaMechanics(text) {
    /** @type {Rec[]} */
    var entries = [];
    /** @type {string[]} */
    var skipped = [];
    /** @type {Rec} */
    var seen = {};
    var raw = typeof text === 'string' ? text : '';
    raw.split('\n').forEach(function (whole, i) {
      var number = i + 1;
      var line = trimField(whole);
      if (!line) return;
      var at = line.indexOf(':');
      if (at < 0) {
        skipped.push(phrase('rounds.mechanics_no_colon', { line: number }));
        return;
      }
      var chiefdom = trimField(line.slice(0, at)), mechanic = trimField(line.slice(at + 1));
      if (!chiefdom || !mechanic) {
        skipped.push(phrase('rounds.mechanics_blank', { line: number }));
        return;
      }
      var key = foldAscii(chiefdom);
      if (own(seen, key)) {
        skipped.push(phrase('rounds.mechanics_repeated', { line: number, chiefdom: chiefdom }));
        return;
      }
      seen[key] = true;
      entries.push({ chiefdom: chiefdom, mechanic: mechanic });
    });
    return { entries: entries, skipped: skipped };
  }

  /** The area mechanic whose round the borehole is on, and how that was
   * found: asset (named on its record), chiefdom (named for its chiefdom)
   * or none (rounds.mechanic_for).
   * @param {Rec} asset
   * @param {Rec[]|null} [mechanics] the entries parseAreaMechanics returns
   * @returns {[string, string]}
   */
  function mechanicFor(asset, mechanics) {
    var named = textField(asset.area_mechanic);
    if (named) return [named, 'asset'];
    var chiefdom = foldAscii(textField(asset.chiefdom));
    if (chiefdom) {
      var list = mechanics || [];
      for (var i = 0; i < list.length; i++) {
        var entry = list[i];
        if (!entry || typeof entry !== 'object' || Array.isArray(entry)) continue;
        var mechanic = textField(entry.mechanic);
        if (mechanic && foldAscii(textField(entry.chiefdom)) === chiefdom) {
          return [mechanic, 'chiefdom'];
        }
      }
    }
    return ['', 'none'];
  }

  /* latitude and longitude from an easting and northing that are both
   * finite numbers, each in its own zone (inferred from the easting where
   * the record names no zone from 1 to 60), or null */
  function roundPosition(asset) {
    var easting = asset.easting, northing = asset.northing, zone = asset.utm_zone;
    if (!finiteNumber(easting) || !finiteNumber(northing)) return null;
    if (!(finiteNumber(zone) && zone === Math.floor(zone) && zone >= 1 && zone <= 60)) {
      zone = inferZoneForSierraLeone(easting);
    }
    var fix = utmToGeographic(easting, northing, zone);
    return fix ? [fix.lat, fix.lon] : null;
  }

  /* as the headworks plate's symbol writes a position */
  function positionText(lat, lon) {
    return pyFixed(Math.abs(lat), 5) + ' ' + (lat >= 0 ? 'N' : 'S') + ', ' +
      pyFixed(Math.abs(lon), 5) + ' ' + (lon >= 0 ? 'E' : 'W');
  }

  function emptyField(value) {
    return value === null || value === undefined || value === '';
  }

  /* the records read as assets, those of one borehole as one, with how many
   * named a borehole already named and how many could not be read */
  function roundRecords(assets) {
    /** @type {Rec} */
    var byId = {};
    /** @type {Rec[]} */
    var order = [];
    var repeated = 0, unreadable = 0;
    (assets || []).forEach(function (raw) {
      var asset = assetFromDict(raw);
      if (!asset) { unreadable += 1; return; }
      if (!own(byId, asset.asset_id)) {
        byId[asset.asset_id] = asset;
        order.push(asset);
        return;
      }
      repeated += 1;
      var first = byId[asset.asset_id], next = asset;
      MERGED_TEXT.forEach(function (name) {
        if (!textField(first[name]) && textField(next[name])) first[name] = next[name];
      });
      MERGED_VALUES.forEach(function (name) {
        if (emptyField(first[name]) && !emptyField(next[name])) first[name] = next[name];
      });
      first.events = mergeEvents(first.asset_id, first.events, next.events);
    });
    return { records: order, repeated: repeated, unreadable: unreadable };
  }

  function byAssetId(a, b) {
    return a.asset_id < b.asset_id ? -1 : (a.asset_id > b.asset_id ? 1 : 0);
  }

  /* the stops in the order of a nearest-neighbour walk, each with the
   * straight-line distance from the one before, in whole metres */
  function roundWalk(stops) {
    var placed = stops.filter(function (s) { return s.placed; });
    var unplaced = stops.filter(function (s) { return !s.placed; }).sort(byAssetId);
    /** @type {Rec[]} */
    var order = [];
    if (placed.length) {
      var here = placed.reduce(function (best, s) {
        return s._first < best._first || (s._first === best._first && byAssetId(s, best) < 0)
          ? s : best;
      });
      here.leg_m = null;
      order.push(here);
      var left = placed.filter(function (s) { return s !== here; });
      while (left.length) {
        var from = here;
        left.forEach(function (s) {
          s._leg = pyRound(geodesicDistanceM(from._where[0], from._where[1],
            s._where[0], s._where[1]));
        });
        here = left.reduce(function (best, s) {
          return s._leg < best._leg || (s._leg === best._leg && byAssetId(s, best) < 0) ? s : best;
        });
        here.leg_m = here._leg;
        order.push(here);
        left = left.filter(function (s) { return s !== here; });
      }
    }
    unplaced.forEach(function (s) { s.leg_m = null; order.push(s); });
    order.forEach(function (s, i) {
      s.order = i + 1;
      /* the working values are not part of the answer: a latitude computed
       * by two engines' trigonometry need not agree to the last bit */
      delete s._leg;
      delete s._first;
      delete s._where;
    });
    return order;
  }

  /** The service rounds of a register of boreholes on the day asOf
   * (rounds.service_rounds): each mechanic's round with its stops in order
   * and the sum of the legs between them, the stops no mechanic is named
   * for last; each stop with the borehole's identifier and what its plate's
   * symbol begins with, where it is, its condition on record and the visits due.
   * @param {Rec[]|null} assets registry records
   * @param {string} asOf the day, YYYY-MM-DD; never read off the clock
   * @param {Rec|null} [schedule] the intervals (serviceSchedule)
   * @param {Rec[]|null} [mechanics] the area mechanics by chiefdom
   * @param {*} [reportUrl] the report address plates are printed with
   *   (service.report_url): with one, a scan of a plate begins with the link
   *   to its report page (PLAN.md step 7.1); one checkReportUrl refuses is
   *   refused here too
   * @returns {Rec}
   */
  function serviceRounds(assets, asOf, schedule, mechanics, reportUrl) {
    var check = checkReportUrl(reportUrl);
    if (check) throw new Error(check);
    var day = roundDay(asOf);
    var today = /** @type {string} */ (dayToIso(day));
    var plan = checkSchedule(Object.assign({}, serviceSchedule(), schedule || {}));
    var read = roundRecords(assets);
    /** @type {Rec} */
    var groups = {};
    var nothingDue = 0, decommissioned = 0;
    read.records.forEach(function (asset) {
      var state = assetState(asset, today, plan);
      if (state.function === 'decommissioned') { decommissioned += 1; return; }
      var due = state.due.filter(function (item) { return ROUND_STATES.indexOf(item.state) >= 0; });
      if (!due.length) { nothingDue += 1; return; }
      var who = mechanicFor(asset, mechanics);
      var where = roundPosition(asset);
      var first = Math.min.apply(null, due.map(function (item) {
        return item.due_on === null ? day : /** @type {number} */ (isoDay(item.due_on));
      }));
      if (!own(groups, who[0])) groups[who[0]] = [];
      var community = textField(asset.community), district = textField(asset.district);
      var place = community || '(unnamed site)';
      groups[who[0]].push({
        order: 0,
        asset_id: asset.asset_id,
        plate: scanStart(asset.asset_id, reportUrl),
        /* as the registry labels a borehole, from the fields as read here */
        label: district ? place + ' (' + district + ')' : place,
        community: community,
        chiefdom: textField(asset.chiefdom),
        district: district,
        placed: where !== null,
        position: where ? positionText(where[0], where[1]) : '',
        mechanic: who[0],
        mechanic_from: who[1],
        function: state.function,
        condition: state.label,
        condition_detail: state.detail,
        due: due.map(function (item) {
          return { key: item.key, title: item.title, state: item.state, due_on: item.due_on,
            detail: item.detail, months: item.months, basis: item.basis };
        }),
        first_due: dayToIso(first),
        leg_m: null,
        _first: first,
        _where: where,
      });
    });
    var names = Object.keys(groups).filter(function (name) { return name; })
      .sort(codePointCompare);
    if (own(groups, '')) names.push('');
    var rounds = names.map(function (name) {
      var stops = roundWalk(groups[name]);
      return {
        mechanic: name,
        stops: stops,
        distance_m: stops.reduce(function (sum, s) { return sum + (s.leg_m === null ? 0 : s.leg_m); }, 0),
        placed: stops.filter(function (s) { return s.placed; }).length,
        unplaced: stops.filter(function (s) { return !s.placed; }).length,
      };
    });
    return {
      as_of: today,
      rounds: rounds,
      n_boreholes: read.records.length,
      n_stops: rounds.reduce(function (sum, r) { return sum + r.stops.length; }, 0),
      n_nothing_due: nothingDue,
      n_decommissioned: decommissioned,
      n_merged: read.repeated,
      n_unreadable: read.unreadable,
      schedule: {
        sanitary_inspection_months: plan.sanitary_inspection_months,
        water_sample_months: plan.water_sample_months,
        grace_days: plan.grace_days,
        routine_inspection_months: plan.routine_inspection_months
      }
    };
  }

  /** What the rounds say as a whole (rounds.rounds_text): the headline and
   * the counts beside it, how a round is put in order, and what is due when.
   * @param {Rec} result what serviceRounds returns
   * @returns {{summary: string[], method: string, intervals: string}}
   */
  function roundsText(result) {
    /** @type {string[]} */
    var summary = [];
    var total = result.n_boreholes, stops = result.n_stops;
    if (!total) {
      summary.push(phrase('rounds.empty'));
    } else if (stops) {
      summary.push(phrase('rounds.headline', { date: result.as_of, total: total, due: stops,
        rounds: result.rounds.length }));
    } else {
      summary.push(phrase('rounds.headline_none', { date: result.as_of, total: total }));
    }
    if (stops && result.n_nothing_due) {
      summary.push(phrase('rounds.nothing_due', { count: result.n_nothing_due }));
    }
    if (result.n_decommissioned) {
      summary.push(phrase('rounds.decommissioned', { count: result.n_decommissioned }));
    }
    if (result.n_merged) summary.push(phrase('rounds.merged', { count: result.n_merged }));
    if (result.n_unreadable) {
      summary.push(phrase('rounds.unreadable', { count: result.n_unreadable }));
    }
    var plan = result.schedule;
    return {
      summary: summary,
      method: phrase('rounds.method'),
      intervals: phrase('rounds.intervals', { sanitary: plan.sanitary_inspection_months,
        sample: plan.water_sample_months, routine: plan.routine_inspection_months,
        grace: plan.grace_days })
    };
  }

  /** What one round says of itself (rounds.round_text).
   * @param {Rec} one a round of serviceRounds
   * @returns {string[]}
   */
  function roundText(one) {
    var name = one.mechanic || phrase('rounds.unassigned');
    var out = [phrase('rounds.round_stops', { mechanic: name, stops: one.stops.length })];
    if (one.placed > 1) out.push(phrase('rounds.round_distance', { km: one.distance_m / 1000 }));
    if (one.unplaced) out.push(phrase('rounds.unplaced', { count: one.unplaced }));
    if (!one.mechanic) out.push(phrase('rounds.round_unassigned'));
    return out;
  }

  /** The labels of a round's table, in order (rounds.round_header).
   * @returns {string[]}
   */
  function roundHeader() {
    var table = phraseTable('rounds.columns');
    return Object.keys(table).map(function (key) { return table[key]; });
  }

  /** A round's stops as the rows of its table (rounds.round_rows).
   * @param {Rec} one a round of serviceRounds
   * @returns {string[][]}
   */
  function roundRows(one) {
    var states = phraseTable('rounds.state');
    return one.stops.map(function (stop) {
      return [String(stop.order), stop.asset_id, stop.community, stop.chiefdom, stop.condition,
        stop.due.map(function (item) {
          return phrase('rounds.due_short', { title: item.title, state: states[item.state] });
        }).join('; '),
        stop.leg_m === null ? '' : phrase('rounds.leg_km', { km: stop.leg_m / 1000 })];
    });
  }

  /** What the round sheet prints for one stop (rounds.stop_sheet): its
   * heading, the details, and for each visit due the sentence saying what
   * is due and why with the boxes for its readings, then the boxes for the
   * visit itself. A box is a row whose last cell is blank.
   * @param {Rec} stop a stop of serviceRounds
   * @returns {Rec}
   */
  function stopSheet(stop) {
    var words = phraseTable('rounds.sheet_details');
    var leg = stop.leg_m !== null ? phrase('rounds.sheet_leg', { km: stop.leg_m / 1000 })
      : (!stop.placed ? phrase('rounds.sheet_no_position') : phrase('rounds.sheet_first'));
    var mechanic = stop.mechanic
      ? stop.mechanic + ' (' + phraseTable('rounds.mechanic_from')[stop.mechanic_from] + ')'
      : phrase('rounds.unassigned');
    var details = [
      [words.identifier, stop.asset_id],
      [words.plate, stop.plate],
      [words.community, stop.community || '-'],
      [words.chiefdom, stop.chiefdom || '-'],
      [words.district, stop.district || '-'],
      [words.position, stop.position || phrase('rounds.sheet_no_position')],
      [words.condition, stop.condition + '. ' + stop.condition_detail],
      [words.leg, leg],
      [words.mechanic, mechanic],
    ];
    var states = phraseTable('rounds.state');
    var value = phrase('rounds.sheet_value');
    var rowsOf = function (table) {
      return Object.keys(table).map(function (key) { return [table[key], '']; });
    };
    var visits = stop.due.map(function (item) {
      var text = phrase('rounds.sheet_due', { title: item.title, state: states[item.state],
        detail: item.detail, basis: item.basis });
      if (item.key === 'inspection') {
        return { text: text,
          header: [phrase('sanitary.col_number'), phrase('sanitary.col_question'),
            phrase('rounds.sheet_yes_no')],
          rows: formQuestions().map(function (question, i) { return [String(i + 1), question, '']; }) };
      }
      return { text: text, header: [item.title, value],
        rows: rowsOf(phraseTable(item.key === 'routine_inspection'
          ? 'rounds.readings_routine' : 'rounds.readings_sample')) };
    });
    return {
      heading: phrase('rounds.sheet_stop', { order: stop.order, place: stop.label }),
      details: details,
      visits: visits,
      visit: { header: [phrase('rounds.sheet_visit'), value],
        rows: rowsOf(phraseTable('rounds.readings_visit')) },
    };
  }

  Object.assign(C, {
    ROUND_STATES: ROUND_STATES, parseAreaMechanics: parseAreaMechanics,
    mechanicFor: mechanicFor, serviceRounds: serviceRounds, roundsText: roundsText,
    roundText: roundText, roundHeader: roundHeader, roundRows: roundRows,
    stopSheet: stopSheet
  });

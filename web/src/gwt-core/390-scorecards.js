
  /* =================================================== contractor scorecards
   * groundwater/scorecards.py (PLAN.md step 6.3). Each project file carries
   * a works record at its top level (worksRecord, read back by cleanWorks):
   * the project's borehole and contractor, the supervision checklist's
   * answers by stage, the drilled metres reconciliation's two figures, the
   * variation orders on its contract and the contract's completion date.
   * The Portfolio page pools the records (scorecardBoreholes), a file saved
   * before the record existed giving its ledger's drilled points, and sets
   * them out by contractor (contractorScorecards, scorecardContent). A
   * figure no record holds is null and reads "not recorded", never nought,
   * and a contractor is ranked, by dry holes against the forecast, only on
   * at least ledger.scorecard_min_boreholes forecast boreholes. Every
   * function is the twin of the one of the same name in snake case, and
   * parity holds them to one another. */

  var SCORECARD_BASES = ['tested', 'recorded_failure', 'recorded_success'];
  var SCORECARD_MONTHS = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august',
    'september', 'october', 'november', 'december'];
  /* an ISO day, with the time of day a date cell can carry after it */
  var SCORECARD_ISO_WRITTEN = /^([0-9]{4}-[0-9]{2}-[0-9]{2})(?:[ T][0-9]{2}:[0-9]{2}(?::[0-9]{2})?)?$/;
  var SCORECARD_DAY_FIRST =
    /^([0-9]{1,2})(?:st|nd|rd|th)?(?:[ \t]+of)?[ \t,./-]+([A-Za-z]+)\.?[ \t,./-]+([0-9]{4})$/i;
  var SCORECARD_MONTH_FIRST = /^([A-Za-z]+)\.?[ \t,./-]+([0-9]{1,2})(?:st|nd|rd|th)?[ \t,./-]+([0-9]{4})$/i;
  /* a checklist stage's key, as the checklist writes them */
  var SCORECARD_STAGE_KEY = /^[a-z][a-z0-9_]*$/;

  /* the month a word names in full or by its first three letters ("Sept" too) */
  function scorecardMonth(word) {
    var w = word.toLowerCase();
    for (var k = 0; k < SCORECARD_MONTHS.length; k++) {
      var name = SCORECARD_MONTHS[k];
      if (w === name || w === name.slice(0, 3) || (k === 8 && w === 'sept')) return k + 1;
    }
    return null;
  }

  function scorecardIsoText(year, month, day) {
    return String(year).padStart(4, '0') + '-' + twoDigits(month) + '-' + twoDigits(day);
  }

  /** scorecards.written_day: the day a date as written on a drilling log
   * names, as YYYY-MM-DD, or null where it cannot be read without a guess:
   * an ISO day (with the time a date cell can carry), or a day with its
   * month by name either way round. A date in figures alone is not read.
   * @param {*} text
   * @returns {string|null} */
  function writtenDay(text) {
    var raw = trimField(text);
    var iso = SCORECARD_ISO_WRITTEN.exec(raw);
    if (iso) {
      var day = isoDay(iso[1]);
      return day === null ? null : iso[1];
    }
    var forms = [[SCORECARD_DAY_FIRST, 1, 2], [SCORECARD_MONTH_FIRST, 2, 1]];
    for (var f = 0; f < forms.length; f++) {
      var found = /** @type {RegExp} */ (forms[f][0]).exec(raw);
      if (!found) continue;
      var month = scorecardMonth(found[/** @type {number} */ (forms[f][2])]);
      if (month === null) return null;
      var year = Number(found[3]), date = Number(found[/** @type {number} */ (forms[f][1])]);
      if (year < 1 || date < 1 || date > daysInMonth(year, month)) return null;
      return scorecardIsoText(year, month, date);
    }
    return null;
  }

  /* days done (as the log writes it) fell after due (YYYY-MM-DD), negative
   * where early, or null where either cannot be read */
  function scorecardDaysLate(due, done) {
    var dueDay = isoDay(due);
    var doneText = writtenDay(done);
    var doneDay = doneText === null ? null : isoDay(doneText);
    if (dueDay === null || doneDay === null) return null;
    return doneDay - dueDay;
  }

  /* drilled metres as typed: a number not below nought, to the centimetre */
  function scorecardMetres(value) {
    var x = ledgerNum(value, 2);
    return x !== null && x >= 0.0 ? x : null;
  }

  function scorecardText(value) { return typeof value === 'string' ? value : ''; }

  /* a contract's completion date as typed, trimmed; '' for anything but
   * text, which Python's twin would write out differently */
  function scorecardDue(value) { return typeof value === 'string' ? trimField(value) : ''; }

  /* the signed and unsigned variation orders on a contract and the value the
   * signed ones add to its sum, as the payment certificate values them, or
   * null where no contract is recorded */
  function scorecardVariationFigures(procurement) {
    if (!isRecord(procurement)) return null;
    var lines = procurement.lines;
    if (!Array.isArray(lines) || !lines.length) return null;
    var contract = { ref: '', lines: lines.filter(isRecord).map(function (line) {
      return { code: trimField(line.code), item: scorecardText(line.item), unit: scorecardText(line.unit),
        quantity: ledgerNum(line.quantity, null) || 0.0, rate_usd: ledgerNum(line.rate_usd, null) || 0.0 };
    }), retention_percent: 10.0, retention_cap_percent: 5.0, advance_percent: 0.0 };
    var raws = procurement.variations;
    var variations = Array.isArray(raws) ? raws.filter(function (v) {
      return isRecord(v) && trimField(v.code) !== '';
    }).map(function (v) {
      return { ref: scorecardText(v.ref), date: scorecardText(v.date), code: trimField(v.code),
        quantity_delta: ledgerNum(v.quantity_delta, null) || 0.0, rate_usd: ledgerNum(v.rate_usd, null),
        reason: scorecardText(v.reason), authorised_by: ledgerName(v.authorised_by),
        item: scorecardText(v.item), unit: scorecardText(v.unit) };
    }) : [];
    var certificate = certify(contract, [], { number: 1, date: '', variations: variations });
    var signed = variations.filter(function (v) { return v.authorised_by; }).length;
    return [signed, variations.length - signed, certificate.variation_usd];
  }

  /* an object's own keys in the order Python's sorted() gives a dict's */
  function scorecardSortedKeys(map) {
    return Object.keys(map).sort(codePointCompare);
  }

  /** scorecards.works_record: what one project records of its contractor's
   * work, or null where it records nothing a scorecard reads. The borehole
   * is the project's completion, or where the project holds no log the
   * outcome its ledger kept; its forecast the chance recorded before
   * drilling at the point it was drilled at; its identifier that point's,
   * else one hashed from its reference, position and place: not from the
   * ledger's identity, which a save made before any prediction was recorded
   * does not have.
   * @param {Rec} site the project's site details
   * @param {DrillingLog|null} log
   * @param {PumpingAnalysis|null} analysis
   * @param {Rec|null} ledger the project's ledger of predictions and outcomes
   * @param {Record<string, string>|null} [answers] the checklist's answers by item id
   * @param {Rec|null} [metres] the reconciliation's logged_m and claimed_m as typed
   * @param {Rec|null} [procurement] the contract's lines, variations and due date, or null
   * @param {Config} [config]
   * @param {Rec[]} [items] the checklist's items, the bundled checklist where omitted
   * @returns {Rec|null} */
  function worksRecord(site, log, analysis, ledger, answers, metres, procurement, config, items) {
    var cfg = config || defaultConfig();
    var contractor = ledgerName((site || {}).contractor);
    var outcome = completionOutcome(log || null, analysis || null, cfg, contractor);
    var held = attachOutcome(ledger || null, outcome, cfg);
    var drilled = null;
    for (var i = 0; i < held.entries.length; i++) {
      if (held.entries[i].outcome !== null) { drilled = held.entries[i]; break; }
    }
    /* a file whose log was not carried with it keeps what its ledger recorded */
    if (outcome === null && drilled !== null) outcome = drilled.outcome;
    var forecast = null;
    if (drilled !== null && drilled.before_outcome && drilled.prediction.odds !== null) {
      var p = drilled.prediction.odds.probability;
      forecast = p !== null && p >= 0.0 && p <= 1.0 ? p : null;
    }

    var given = isRecord(answers) ? /** @type {Rec} */ (answers) : {};
    /** @type {Rec} */
    var stages = {};
    (items || loadChecklists()).forEach(function (item) {
      var status = own(given, item.item_id) ? given[item.item_id] : undefined;
      if (status !== 'yes' && status !== 'no') return;
      if (!own(stages, item.checklist)) stages[item.checklist] = { answered: 0, failed: [] };
      stages[item.checklist].answered += 1;
      if (status === 'no') stages[item.checklist].failed.push(item.item_id);
    });
    /** @type {Rec} */
    var checklist = {};
    scorecardSortedKeys(stages).forEach(function (key) { checklist[key] = stages[key]; });

    var logged = isRecord(metres) ? scorecardMetres(/** @type {Rec} */ (metres).logged_m) : null;
    var claimed = isRecord(metres) ? scorecardMetres(/** @type {Rec} */ (metres).claimed_m) : null;
    var figures = scorecardVariationFigures(procurement);
    if (outcome === null && !Object.keys(checklist).length && logged === null && claimed === null &&
        figures === null) return null;
    var community = String((site || {}).community || '');
    var district = String((site || {}).district || '');
    var ref = outcome !== null ? outcome.borehole_ref : '';
    var at = outcome || {};
    var rid = drilled !== null ? drilled.id
      : pointId('borehole ' + ref, at.easting === undefined ? null : at.easting,
        at.northing === undefined ? null : at.northing, at.utm_zone === undefined ? null : at.utm_zone,
        community, district);
    return {
      borehole_ref: ref,
      checklist: checklist,
      claimed_m: claimed,
      community: community,
      completion_date: outcome !== null ? outcome.completion_date : '',
      completion_due: figures !== null ? scorecardDue(/** @type {Rec} */ (procurement).due) : '',
      contract: figures !== null,
      contractor: outcome !== null ? outcome.contractor : contractor,
      district: district,
      drilled: outcome !== null,
      forecast: forecast,
      id: rid,
      logged_m: logged,
      success: outcome !== null ? outcome.success : null,
      success_basis: outcome !== null ? outcome.success_basis : null,
      variation_usd: figures !== null ? ledgerNum(figures[2], 2) : null,
      variations_signed: figures !== null ? figures[0] : null,
      variations_unsigned: figures !== null ? figures[1] : null,
    };
  }

  /* a whole count not below nought, or null */
  function scorecardCount(value) {
    return typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : null;
  }

  /** scorecards.clean_works: a works record as read from a file, in the
   * shape worksRecord writes, or null where it is not one. A field of the
   * wrong kind is blank, a stage that fails more items than it answered is
   * left out, and counts that do not go with a contract are dropped.
   * @param {*} raw
   * @returns {Rec|null} */
  function cleanWorks(raw) {
    if (!isRecord(raw) || typeof raw.id !== 'string' || !raw.id) return null;
    /** @type {Rec} */
    var checklist = {};
    var stages = isRecord(raw.checklist) ? raw.checklist : {};
    scorecardSortedKeys(stages).forEach(function (stage) {
      var held = stages[stage];
      if (!SCORECARD_STAGE_KEY.test(stage) || !isRecord(held)) return;
      var answered = scorecardCount(held.answered);
      var failed = Array.isArray(held.failed) ? held.failed.filter(function (f, k, all) {
        return typeof f === 'string' && f !== '' && all.indexOf(f) === k;
      }) : [];
      if (answered === null || answered === 0 || failed.length > answered) return;
      checklist[stage] = { answered: answered, failed: failed };
    });
    var contract = raw.contract === true;
    var success = typeof raw.success === 'boolean' ? raw.success : null;
    var basis = success !== null && SCORECARD_BASES.indexOf(raw.success_basis) >= 0 ? raw.success_basis : null;
    var forecast = ledgerNum(raw.forecast, 3);
    var signed = scorecardCount(raw.variations_signed), unsigned = scorecardCount(raw.variations_unsigned);
    var value = ledgerNum(raw.variation_usd, 2);
    if (!contract || signed === null || unsigned === null || value === null) {
      contract = false; signed = null; unsigned = null; value = null;
    }
    return {
      borehole_ref: scorecardText(raw.borehole_ref),
      checklist: checklist,
      claimed_m: scorecardMetres(raw.claimed_m),
      community: scorecardText(raw.community),
      completion_date: scorecardText(raw.completion_date),
      completion_due: contract ? scorecardDue(raw.completion_due) : '',
      contract: contract,
      contractor: ledgerName(raw.contractor),
      district: scorecardText(raw.district),
      drilled: raw.drilled === true,
      forecast: forecast !== null && forecast >= 0.0 && forecast <= 1.0 ? forecast : null,
      id: raw.id,
      logged_m: scorecardMetres(raw.logged_m),
      success: success,
      success_basis: basis,
      variation_usd: value,
      variations_signed: signed,
      variations_unsigned: unsigned,
    };
  }

  /* a borehole a file saved before the works record holds in its ledger
   * alone: its contractor, outcome and forecast, and nothing else recorded */
  function scorecardLedgerRow(entry) {
    var outcome = entry.outcome, odds = entry.prediction.odds;
    var p = odds !== null && entry.before_outcome ? odds.probability : null;
    return {
      borehole_ref: outcome.borehole_ref, checklist: {}, claimed_m: null,
      community: entry.point.community, completion_date: outcome.completion_date,
      completion_due: '', contract: false, contractor: outcome.contractor,
      district: entry.point.district, drilled: true,
      forecast: p !== null && p >= 0.0 && p <= 1.0 ? p : null, id: entry.id, logged_m: null,
      success: outcome.success, success_basis: outcome.success !== null ? outcome.success_basis : null,
      variation_usd: null, variations_signed: null, variations_unsigned: null,
      project: entry.project, source: 'ledger',
    };
  }

  /* how many of the scorecard's measures a borehole's record holds */
  function scorecardRecorded(row) {
    return [row.logged_m !== null && row.claimed_m !== null, Object.keys(row.checklist).length > 0,
      row.contract, row.completion_due !== '', row.success !== null, row.forecast !== null]
      .filter(Boolean).length;
  }

  function scorecardRicher(row, have) {
    var a = row.source === 'works', b = have.source === 'works';
    if (a !== b) return a;
    return scorecardRecorded(row) > scorecardRecorded(have);
  }

  /** scorecards.scorecard_boreholes: the boreholes drilled across a
   * portfolio's project files, each once: a file's works record where it has
   * one, else its ledger's drilled points, pooled as the ledger pools them.
   * Each carries its file's label as project and its source (works, ledger).
   * @param {Array<Array<*>>} files [project label, works record, ledger] for each file
   * @returns {Rec[]} */
  function scorecardBoreholes(files) {
    /** @type {Map<string, Rec>} */
    var kept = new Map();
    function keep(row) {
      var have = kept.get(row.id);
      if (have === undefined || scorecardRicher(row, have)) kept.set(row.id, row);
    }
    /** @type {Array<Array<*>>} */
    var older = [];
    files.forEach(function (file) {
      var record = cleanWorks(file[1]);
      if (record === null) older.push([file[0], file[2]]);
      else if (record.drilled) keep(Object.assign(record, { project: String(file[0] || ''), source: 'works' }));
    });
    poolLedgers(older).forEach(function (entry) {
      if (entry.outcome !== null) keep(scorecardLedgerRow(entry));
    });
    return Array.from(kept.values());
  }

  /* one contractor's scorecard over its boreholes */
  function scorecardCard(name, rows, stages, minimum, order) {
    var pairs = rows.filter(function (r) { return r.logged_m !== null && r.claimed_m !== null; });
    var logged = calibrationSum(pairs.map(function (r) { return r.logged_m; }));
    var claimed = calibrationSum(pairs.map(function (r) { return r.claimed_m; }));
    var metres = {
      n: pairs.length,
      logged_m: pairs.length ? pyRound(logged, 2) : null,
      claimed_m: pairs.length ? pyRound(claimed, 2) : null,
      over_m: pairs.length ? pyRound(claimed - logged, 2) : null,
      beyond: pairs.filter(function (r) { return !metresReconciliationCheck(r.logged_m, r.claimed_m).passed; }).length,
    };

    var checked = rows.filter(function (r) {
      return stages.some(function (stage) { return own(r.checklist, stage); });
    });
    /** @type {Map<string, Array<*>>} */
    var failures = new Map();
    var failedTotal = 0, withFailures = 0;
    checked.forEach(function (r) {
      var failed = [];
      stages.forEach(function (stage) {
        if (!own(r.checklist, stage)) return;
        r.checklist[stage].failed.forEach(function (item) { failed.push([stage, item]); });
      });
      failedTotal += failed.length;
      withFailures += failed.length ? 1 : 0;
      failed.forEach(function (key) {
        var at = key[0] + '\u0000' + key[1];
        var have = failures.get(at);
        if (have) have[2] += 1; else failures.set(at, [key[0], key[1], 1]);
      });
    });
    var listed = Array.from(failures.values()).sort(function (a, b) {
      var sa = stages.indexOf(a[0]), sb = stages.indexOf(b[0]);
      if (sa !== sb) return sa - sb;
      var oa = order.has(a[1]) ? order.get(a[1]) : order.size;
      var ob = order.has(b[1]) ? order.get(b[1]) : order.size;
      if (oa !== ob) return oa - ob;
      return codePointCompare(a[1], b[1]);
    });
    var checks = { n: checked.length, with_failures: withFailures, failed: failedTotal, items: listed };

    var contracts = rows.filter(function (r) { return r.contract; });
    var variations = {
      n: contracts.length,
      signed: contracts.length ? contracts.reduce(function (t, r) { return t + r.variations_signed; }, 0) : null,
      unsigned: contracts.length ? contracts.reduce(function (t, r) { return t + r.variations_unsigned; }, 0)
        : null,
      value_usd: contracts.length ? pyRound(calibrationSum(contracts.map(function (r) {
        return r.variation_usd;
      })), 2) : null,
    };

    var timed = [], unread = 0;
    rows.forEach(function (r) {
      if (!r.completion_due) return;
      var days = scorecardDaysLate(r.completion_due, r.completion_date);
      if (days === null) unread += 1; else timed.push(days);
    });
    var late = timed.filter(function (d) { return d > 0; });
    var time = {
      n: timed.length, late: late.length,
      days_late: timed.length ? late.reduce(function (t, d) { return t + d; }, 0) : null,
      most_days: late.length ? Math.max.apply(null, late) : null, unread: unread,
    };

    var known = rows.filter(function (r) { return r.success !== null; });
    var forecast = known.filter(function (r) { return r.forecast !== null; });
    var expected = calibrationSum(forecast.map(function (r) { return 1.0 - r.forecast; }));
    var found = forecast.filter(function (r) { return r.success === false; }).length;
    var span = forecast.length ? binomialRange(forecast.length, expected / forecast.length) : null;
    var verdict;
    if (forecast.length < minimum || span === null) verdict = 'too_few';
    else if (found > span[1]) verdict = 'more';
    else if (found < span[0]) verdict = 'fewer';
    else verdict = 'within';
    var dry = {
      known: known.length, dry: known.filter(function (r) { return r.success === false; }).length,
      forecast: forecast.length, forecast_dry: found,
      expected: forecast.length ? pyRound(expected, 2) : null, range: span, verdict: verdict,
    };
    var ranked = !!name && forecast.length >= minimum;
    return {
      contractor: name || phrase('scorecards.no_contractor'),
      recorded: !!name,
      boreholes: rows.length,
      from_ledger: rows.filter(function (r) { return r.source === 'ledger'; }).length,
      metres: metres, checks: checks, variations: variations, time: time, dry: dry,
      measure: ranked ? pyRound((found - expected) / forecast.length, 3) : null,
      rank: null,
      unranked: ranked ? null : (name ? 'too_few' : 'no_contractor'),
    };
  }

  /* the fewest forecast boreholes a contractor is judged and ranked on, and
   * never fewer than one, since one with no forecast has nothing to be
   * ranked by */
  function scorecardMinimum(cfg) {
    return Math.max(1, Math.trunc(Number(cfg.ledger.scorecard_min_boreholes)));
  }

  /* the checklist stages whose items are the contractor's acceptance checks,
   * each once, so a stage named twice does not count its failures twice */
  function scorecardStages(cfg) {
    var named = (cfg.ledger.scorecard_stages || []).map(function (s) { return String(s); });
    return named.filter(function (s, k) { return named.indexOf(s) === k; });
  }

  /** scorecards.contractor_scorecards: a scorecard for each contractor of
   * scorecardBoreholes, the boreholes naming none together: its figures,
   * each with the number of boreholes it rests on and null where none
   * records it; the ranking measure and rank (on at least
   * ledger.scorecard_min_boreholes forecast boreholes) or why it has none.
   * The ranked first by rank and name, then the rest, the most boreholes
   * first, and the boreholes naming no contractor last.
   * @param {Rec[]} boreholes
   * @param {Config} [config]
   * @param {Rec[]} [items] the checklist's items, the bundled checklist where omitted
   * @returns {Rec[]} */
  function contractorScorecards(boreholes, config, items) {
    var cfg = config || defaultConfig();
    var minimum = scorecardMinimum(cfg);
    var stages = scorecardStages(cfg);
    /** @type {Map<string, number>} */
    var order = new Map();
    (items || loadChecklists()).forEach(function (item, k) { order.set(item.item_id, k); });
    /** @type {Map<string, Rec[]>} */
    var groups = new Map();
    boreholes.forEach(function (row) {
      var name = ledgerName(row.contractor);
      var group = groups.get(name);
      if (group) group.push(row); else groups.set(name, [row]);
    });
    /** @type {Rec[]} */
    var cards = [];
    groups.forEach(function (rows, name) { cards.push(scorecardCard(name, rows, stages, minimum, order)); });
    var measures = cards.filter(function (c) { return c.measure !== null; }).map(function (c) { return c.measure; });
    cards.forEach(function (card) {
      if (card.measure === null) return;
      card.rank = 1 + measures.filter(function (m) { return m < card.measure; }).length;
    });
    cards.sort(function (a, b) {
      var ar = a.rank === null, br = b.rank === null;
      if (ar !== br) return ar ? 1 : -1;
      if (a.recorded !== b.recorded) return a.recorded ? -1 : 1;
      if (!ar && a.rank !== b.rank) return a.rank - b.rank;
      if (ar && a.boreholes !== b.boreholes) return b.boreholes - a.boreholes;
      return codePointCompare(a.contractor, b.contractor);
    });
    return cards;
  }

  /* a difference in metres with its sign: "+4", "-2.5", "0" */
  function scorecardSignedG(value) {
    if (value === 0) return '0';
    return (value > 0 ? '+' : '') + formatG(value);
  }

  /* a sum of money with its sign outside the currency, as the payment
   * certificate writes it */
  function scorecardSignedMoney(value) {
    return (value < 0 ? '-' : '+') + money0(Math.abs(value));
  }

  function scorecardMetresCell(m) {
    if (!m.n) return phrase('scorecards.not_recorded');
    var text = phrase('scorecards.metres_cell', { over: scorecardSignedG(m.over_m), n: m.n,
      claimed: m.claimed_m, logged: m.logged_m });
    if (m.beyond) {
      text += '; ' + phrase('scorecards.metres_beyond', { k: m.beyond, tolerance: METRES_TOLERANCE_M });
    }
    return text;
  }

  function scorecardChecksCell(c) {
    if (!c.n) return phrase('scorecards.not_recorded');
    if (!c.failed) return phrase('scorecards.checks_cell_none', { n: c.n });
    return phrase('scorecards.checks_cell', { failed: c.failed, k: c.with_failures, n: c.n });
  }

  function scorecardVariationsCell(v) {
    if (!v.n) return phrase('scorecards.not_recorded');
    var text = v.signed
      ? phrase('scorecards.variations_cell', { signed: v.signed, value: scorecardSignedMoney(v.value_usd), n: v.n })
      : phrase('scorecards.variations_cell_none', { n: v.n });
    if (v.unsigned) text += '; ' + phrase('scorecards.variations_unsigned', { k: v.unsigned });
    return text;
  }

  function scorecardTimeCell(t) {
    var parts = [];
    if (t.n) {
      parts.push(t.late
        ? phrase('scorecards.time_cell', { late: t.late, n: t.n, days: t.days_late, most: t.most_days })
        : phrase('scorecards.time_cell_none', { n: t.n }));
    }
    if (t.unread) parts.push(phrase('scorecards.time_unread', { k: t.unread }));
    return parts.length ? parts.join('; ') : phrase('scorecards.not_recorded');
  }

  function scorecardDryCell(d) {
    if (!d.known) return phrase('scorecards.dry_cell_unknown');
    var text = phrase('scorecards.dry_cell', { dry: d.dry, known: d.known });
    if (d.forecast) {
      text += '; ' + phrase('scorecards.dry_forecast', { fdry: d.forecast_dry, f: d.forecast,
        expected: d.expected, low: d.range[0], high: d.range[1] });
    }
    return text;
  }

  function scorecardRankCell(card, minimum) {
    if (card.rank !== null) return String(card.rank);
    if (card.unranked === 'no_contractor') return phrase('scorecards.rank_no_contractor');
    return phrase('scorecards.rank_too_few', { f: card.dry.forecast, minimum: minimum });
  }

  /* the stages' titles in a sentence, in lower case */
  function scorecardStagesText(stages) {
    var titles = stages.map(function (s) { return stageTitle(s).toLowerCase(); });
    if (titles.length < 2) return titles.join('');
    if (titles.length === 2) return titles[0] + ' and ' + titles[1];
    return titles.slice(0, -1).join(', ') + ', and ' + titles[titles.length - 1];
  }

  /** scorecards.scorecard_content: everything the contractor scorecards say,
   * as plain data the two document writers lay out as the calibration report
   * is laid out: the title and subtitle, the cover's rows, the summary, the
   * sections (paragraphs, tables, bullets; cards holds the scorecards'
   * table and checks the checks that failed) and the references.
   * @param {Array<Array<*>>} files [project label, works record, ledger] for each file
   * @param {string} [issuedOn] the date the report is issued ('' to leave it off)
   * @param {Config} [config]
   * @returns {Rec} */
  function scorecardContent(files, issuedOn, config) {
    var cfg = config || defaultConfig();
    var minimum = scorecardMinimum(cfg);
    var stages = scorecardStages(cfg);
    var items = loadChecklists();
    var boreholes = scorecardBoreholes(files);
    var cards = contractorScorecards(boreholes, cfg, items);
    var named = cards.filter(function (c) { return c.recorded; });
    var rows = [[phrase('scorecards.row_projects'), String(files.length)],
      [phrase('scorecards.row_boreholes'), String(boreholes.length)],
      [phrase('scorecards.row_contractors'), String(named.length)]];
    var issued = ledgerName(issuedOn);
    if (issued) rows.push([phrase('scorecards.row_issued'), issued]);

    var summary = [];
    if (!boreholes.length) {
      summary.push(phrase('scorecards.summary_none'));
    } else {
      summary.push(named.length
        ? phrase('scorecards.summary_counts', { boreholes: boreholes.length, contractors: named.length,
          projects: files.length })
        : phrase('scorecards.summary_counts_unnamed', { boreholes: boreholes.length, projects: files.length }));
      var unnamed = cards.filter(function (c) { return !c.recorded; })
        .reduce(function (t, c) { return t + c.boreholes; }, 0);
      if (unnamed) summary.push(phrase('scorecards.summary_unnamed', { n: unnamed }));
      var older = cards.reduce(function (t, c) { return t + c.from_ledger; }, 0);
      if (older) summary.push(phrase('scorecards.summary_ledger_only', { n: older }));
      var ranked = cards.filter(function (c) { return c.rank !== null; }).length;
      summary.push(ranked ? phrase('scorecards.summary_ranked', { ranked: ranked, minimum: minimum })
        : phrase('scorecards.summary_unranked', { minimum: minimum }));
      summary.push(phrase('scorecards.summary_n'));
    }

    var sections = [];
    if (boreholes.length) {
      var table = calibrationSection('cards', phrase('scorecards.cards_heading'));
      table.paragraphs.push(phrase('scorecards.cards_intro'));
      table.tables.push({
        header: [phrase('scorecards.col_contractor'), phrase('scorecards.col_boreholes'),
          phrase('scorecards.col_metres'), phrase('scorecards.col_checks'), phrase('scorecards.col_variations'),
          phrase('scorecards.col_time'), phrase('scorecards.col_dry'), phrase('scorecards.col_rank')],
        rows: cards.map(function (c) {
          return [c.contractor, String(c.boreholes), scorecardMetresCell(c.metres), scorecardChecksCell(c.checks),
            scorecardVariationsCell(c.variations), scorecardTimeCell(c.time), scorecardDryCell(c.dry),
            scorecardRankCell(c, minimum)];
        }),
        caption: phrase('scorecards.cards_table'),
      });
      sections.push(table);

      var checks = calibrationSection('checks', phrase('scorecards.checks_heading'));
      checks.paragraphs.push(stages.length ? phrase('scorecards.checks_intro', { stages: scorecardStagesText(stages) })
        : phrase('scorecards.checks_no_stages'));
      /** @type {Map<string, string>} */
      var texts = new Map();
      items.forEach(function (item) { texts.set(item.item_id, item.text); });
      var failed = [];
      cards.forEach(function (c) {
        c.checks.items.forEach(function (it) {
          failed.push([c.contractor, stageTitle(it[0]), texts.has(it[1]) ? texts.get(it[1]) : it[1], String(it[2])]);
        });
      });
      if (failed.length) {
        checks.tables.push({
          header: [phrase('scorecards.col_contractor'), phrase('scorecards.col_stage'),
            phrase('scorecards.col_check'), phrase('scorecards.col_failed_on')],
          rows: failed,
          caption: phrase('scorecards.checks_table'),
        });
      } else if (cards.some(function (c) { return c.checks.n > 0; })) {
        checks.paragraphs.push(phrase('scorecards.checks_none'));
      } else if (stages.length) {
        checks.paragraphs.push(phrase('scorecards.checks_unchecked'));
      }
      sections.push(checks);

      var dry = calibrationSection('dry', phrase('scorecards.dry_heading'));
      dry.paragraphs.push(phrase('scorecards.dry_intro', { rate: Number(cfg.odds.success_yield_m3_per_h) }),
        phrase('scorecards.dry_range', { minimum: minimum }), phrase('scorecards.dry_rank', { minimum: minimum }));
      var verdicts = phraseTable('scorecards.dry_verdict');
      var none = phrase('scorecards.not_recorded');
      dry.tables.push({
        header: [phrase('scorecards.col_contractor'), phrase('scorecards.col_known'),
          phrase('scorecards.col_dry_found'), phrase('scorecards.col_forecast'),
          phrase('scorecards.col_dry_forecast'), phrase('scorecards.col_expected'),
          phrase('scorecards.col_range'), phrase('scorecards.col_verdict')],
        rows: cards.map(function (c) {
          var d = c.dry;
          return [c.contractor, String(d.known), String(d.dry), String(d.forecast),
            d.forecast ? String(d.forecast_dry) : none,
            d.forecast ? formatG(d.expected) : none,
            d.forecast ? phrase('scorecards.dry_range_cell', { low: d.range[0], high: d.range[1] }) : none,
            verdicts[d.verdict]];
        }),
        caption: phrase('scorecards.dry_table'),
      });
      sections.push(dry);
    }

    var method = calibrationSection('method', phrase('scorecards.method_heading'));
    method.bullets.push(
      phrase('scorecards.method_boreholes'),
      phrase('scorecards.method_metres', { tolerance: METRES_TOLERANCE_M }),
      stages.length ? phrase('scorecards.method_checks', { stages: scorecardStagesText(stages) })
        : phrase('scorecards.checks_no_stages'),
      phrase('scorecards.method_variations'),
      phrase('scorecards.method_time'),
      phrase('scorecards.method_dry'),
      phrase('scorecards.method_names'),
      phrase('scorecards.method_minimum', { minimum: minimum }),
      phrase('scorecards.method_report'));
    sections.push(method);
    var citations = phraseTable('references.citations');
    return {
      title: phrase('scorecards.title'),
      subtitle: phrase('scorecards.subtitle'),
      rows: rows,
      summary: summary,
      sections: sections,
      references: [citations.rwsn_supervision],
    };
  }

  Object.assign(C, {
    writtenDay: writtenDay, worksRecord: worksRecord, cleanWorks: cleanWorks,
    scorecardBoreholes: scorecardBoreholes, contractorScorecards: contractorScorecards,
    scorecardContent: scorecardContent,
  });

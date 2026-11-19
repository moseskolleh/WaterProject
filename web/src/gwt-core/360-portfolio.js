
  /* ================================================================ portfolio
   * groundwater/portfolio.py. A water manager oversees many boreholes, not
   * one. Each saved project file carries a small headline summary; this turns
   * a list of those summaries into a comparison table, mapped points coloured
   * by status, and programme statistics.
   */

  /* groundwater/site_status.py. Field sheets carry the status as free text,
   * and substring matching cannot read it: "complete" is inside "incomplete",
   * "productive" is inside "unproductive", "sit" is inside "visited". Every
   * one of those read as a producing borehole, so a run of dry holes reported
   * as successes and painted green on the national map. Known phrasings are
   * listed; the rest are matched by word-boundary rules ordered so a negation
   * is always seen before the word it negates; anything still unrecognised
   * lands in "other" rather than being guessed at. */

  var STATUS_COLORS = {
    successful: '#2E7D5B', dry: '#B23A2E', sited: '#17527E',
    in_progress: '#C1772A', other: '#6B7785',
  };
  var STATUS_LABELS = {
    successful: 'Successful', dry: 'Dry / failed',
    sited: 'Sited (not drilled)', in_progress: 'In progress',
    other: 'Status not recognised',
  };

  var LEGACY_STATUS_MAP = {
    successful: 'successful', success: 'successful', completed: 'successful',
    complete: 'successful', productive: 'successful', equipped: 'successful',
    commissioned: 'successful', 'handed over': 'successful',
    dry: 'dry', 'dry hole': 'dry', failed: 'dry', failure: 'dry',
    unsuccessful: 'dry', 'not successful': 'dry', unproductive: 'dry',
    'non productive': 'dry', abandoned: 'dry', 'no water': 'dry',
    'completed dry': 'dry',
    sited: 'sited', siting: 'sited', surveyed: 'sited', 'not drilled': 'sited',
    incomplete: 'in_progress', 'not completed': 'in_progress',
    uncompleted: 'in_progress', 'in progress': 'in_progress',
    ongoing: 'in_progress', drilling: 'in_progress', pending: 'in_progress',
    'on hold': 'in_progress',
  };

  /* Ordered, first match wins. The order is load-bearing: every rule that
   * recognises a negation must be tried before the word being negated. */
  /** @type {Array<[RegExp, string]>} */
  var STATUS_RULES = [
    [/\b(dry|no\s+water|water\s+not\s+struck|failed|failure|unsuccessful|not\s+successful|abandon\w*|collapsed|backfilled|plugged|caved)\b/, 'dry'],
    [/\b(un|non|not)[\s-]*(productive|producing)\b|\b(low|poor|insufficient|inadequate|marginal|nil)\s+(yield|productivity|production)\b|\bproductivity\s+(low|poor)\b/, 'dry'],
    [/\b(in|un)complet\w*\b|\bnot\s+complet\w*\b|\b(partially|part|partly)\s+complet\w*\b/, 'in_progress'],
    [/\b(in\s+progress|ongoing|under\s+(construction|way|test\w*)|drilling|pending|awaiting|suspended|on\s+hold|deferred|standing\s+by|rework)\b/, 'in_progress'],
    [/\bsit(e|ed|ing)\b|\b(surveyed|survey\s+complete|geophysics\s+complete|recommended\s+for\s+drilling|to\s+be\s+drilled|not\s+drilled)\b/, 'sited'],
    [/\bsuccess(ful)?\b|\bcomplet(e|ed)\b|\bproductive\b|\b(equipped|commissioned|handed\s+over|operational|functional)\b/, 'successful'],
  ];

  /**
   * @param {*} raw
   * @returns {string}
   */
  function normaliseStatus(raw) {
    var text = String(raw === null || raw === undefined ? '' : raw)
      .toLowerCase().replace(/[_/\\|,;()[\].–—-]+/g, ' ');
    return text.replace(/\s+/g, ' ').trim();
  }

  /**
   * @param {string} value
   * @returns {string}
   */
  function statusLabel(value) {
    return STATUS_LABELS[value] || STATUS_LABELS.other;
  }

  /**
   * @param {string} value
   * @returns {string}
   */
  function statusColor(value) {
    return STATUS_COLORS[value] || STATUS_COLORS.other;
  }

  /** Classify free text, or null when it is not recognised.
   * @param {*} raw
   * @returns {string|null}
   */
  function classifyStatusText(raw) {
    var key = normaliseStatus(raw);
    if (!key) return null;
    if (own(LEGACY_STATUS_MAP, key)) return LEGACY_STATUS_MAP[key];
    /* "not sited" is a negation, not a siting */
    if (/\bnot\s+sited\b/.test(key)) return null;
    for (var i = 0; i < STATUS_RULES.length; i++) {
      if (STATUS_RULES[i][0].test(key)) return STATUS_RULES[i][1];
    }
    return null;
  }

  /**
   * @param {Rec|null} summary a project summary
   * @returns {string}
   */
  function classifyStatus(summary) {
    var raw = String((summary && summary.status) || '').trim();
    if (!raw) {
      return (summary && (summary.safe_yield_m3_per_h || summary.total_depth_m))
        ? 'sited' : 'other';
    }
    return classifyStatusText(raw) || 'other';
  }

  /* portfolio._NUMBER_TEXT: a number written as text as Python's float()
   * reads one - a sign, digits with an underscore allowed between two of
   * them, a point and an exponent - spelt out so the two engines read the
   * same texts (Number() also reads '0x10' and a blank) */
  var SUMMARY_NUMBER_TEXT = /^[+-]?(\d(_?\d)*(\.(\d(_?\d)*)?)?|\.\d(_?\d)*)([eE][+-]?\d(_?\d)*)?$/;

  /* portfolio._num: a summary's number as a finite number, or null for
   * anything that is not one. A number written as text, with its ASCII white
   * space trimmed, is read; a hand-edited "52 m" is blank, never NaN. */
  function summaryNum(value) {
    var n;
    if (typeof value === 'number') {
      n = value;
    } else if (typeof value === 'string') {
      var text = value.replace(/^[ \t\n\r\f\v]+|[ \t\n\r\f\v]+$/g, '');
      if (!SUMMARY_NUMBER_TEXT.test(text)) return null;
      n = Number(text.replace(/_/g, ''));
    } else {
      return null;
    }
    return isFinite(n) ? n : null;
  }

  /** Whether a summary's easting and northing are a longitude and a
   * latitude typed into the UTM boxes, by the rule the site page reads them
   * by (utmBoxesHoldDegrees): portfolio.summary_holds_degrees.
   * @param {Rec|null} summary a project summary
   * @returns {boolean}
   */
  function summaryHoldsDegrees(summary) {
    var easting = summaryNum(summary && summary.easting), northing = summaryNum(summary && summary.northing);
    return !!(easting && northing) && utmBoxesHoldDegrees(easting, northing);
  }

  /** Where a project summary is: portfolio._latlon. The portfolio map, the
   * site detail and the desk study all place a project by this.
   * @param {Rec|null} summary a project summary
   * @returns {{lat: number, lon: number}|null}
   */
  function summaryLatLon(summary) {
    if (!summary) return null;
    /* a value a project file carries that is no number ("52 m") is no
     * position, as portfolio._num reads it */
    var easting = summaryNum(summary.easting), northing = summaryNum(summary.northing);
    if (!easting || !northing) return null;
    /* Degrees are no position in metres, as sitePosition reads them: read
     * as metres they put the project on the equator, 940 km off, so the
     * desk study left it out of the projects near its site without a word
     * and the portfolio map drew it in the Gulf of Guinea. */
    if (utmBoxesHoldDegrees(easting, northing)) return null;
    /* the same fallback SiteMetadata.utm uses: a hard-coded zone dropped every
     * zone-less project six degrees off, into the Atlantic and off the map */
    var zone = Math.trunc(summaryNum(summary.utm_zone) || 0) || inferZoneForSierraLeone(easting);
    try {
      var at = utmToGeographic(easting, northing, zone);
      return at && isFinite(at.lat) && isFinite(at.lon) ? at : null;
    } catch (e) { return null; }
  }

  /* The verdict vocabulary written by the current code. An older project file
   * carries the three-value one and is translated on read. */
  var VERDICT_SCHEMA = 2;

  /* "fail" was unambiguously a health exceedance. "aesthetic" was written by
   * code whose aesthetic bucket also held national-standard exceedances, so
   * it may be a concealed compliance failure and must not be shown as merely
   * a matter of taste - it is read as unproven, which is fail-closed. */
  var LEGACY_VERDICTS = {
    fail: 'health_fail', aesthetic: 'indeterminate', pass: 'pass',
  };

  /** Returns [state, fromLegacyFile]; state is null when the project carries
   * no water quality result at all.
   * @param {Rec|null} summary a project summary
   * @returns {[string|null, boolean]}
   */
  function summaryVerdictState(summary) {
    var raw = String((summary && summary.water_verdict) || '').trim().toLowerCase();
    if (!raw) return [null, false];
    /* read as every summary number is (summaryNum), as Python reads it */
    var schema = summaryNum(summary ? summary.verdict_schema : null) || 0;
    if (schema >= VERDICT_SCHEMA) {
      return [own(VERDICT_SHORT, raw) ? raw : null, false];
    }
    return [own(LEGACY_VERDICTS, raw) ? LEGACY_VERDICTS[raw] : null, true];
  }

  /** @param {Rec[]|null} summaries project summaries */
  function portfolioRows(summaries) {
    return (summaries || []).map(function (s) {
      var read = summaryVerdictState(s);
      var water = read[0] ? (VERDICT_SHORT[read[0]] || '') : '';
      /* An asterisk rather than a silent reinterpretation: the value was
       * translated from an older file and the reader should know. */
      if (water && read[1]) water += '*';
      var depth = summaryNum(s.total_depth_m), safe = summaryNum(s.safe_yield_m3_per_h);
      var cost = summaryNum(s.cost_per_meter_usd);
      return {
        Community: s.community || '(unnamed)',
        District: s.district || '',
        Status: statusLabel(classifyStatus(s)),
        'Depth (m)': depth ? pyRound(depth, 1) : null,
        'Safe yield (m3/h)': safe ? pyRound(safe, 2) : null,
        Water: water,
        'Cost/m (USD)': cost ? pyRound(cost, 0) : null,
      };
    });
  }

  /** @param {Rec[]|null} summaries project summaries */
  function portfolioPoints(summaries) {
    var points = [];
    (summaries || []).forEach(function (s) {
      var latlon = summaryLatLon(s);
      if (!latlon) return;
      points.push({
        label: s.community || 'site', lat: latlon.lat, lon: latlon.lon,
        status: classifyStatus(s),
      });
    });
    return points;
  }

  /** "1. Rokel (Port Loko)" - the index keeps a selector unambiguous when two
   * sites share a community name.
   * @param {Rec|null} summary a project summary
   * @param {number|null} [index]
   * @returns {string}
   */
  function portfolioSiteLabel(summary, index) {
    var community = (summary && summary.community) || '(unnamed site)';
    var district = summary && summary.district;
    var label = district ? community + ' (' + district + ')' : community;
    return index === undefined || index === null
      ? label : (index + 1) + '. ' + label;
  }

  /**
   * @param {Rec} summary a project summary
   * @returns {Array<[string, *]>}
   */
  function portfolioSiteDetail(summary) {
    var rows = [];
    function add(label, value) {
      if (value !== null && value !== undefined && value !== '') rows.push([label, value]);
    }
    add('Community', summary.community);
    add('District', summary.district);
    add('Chiefdom', summary.chiefdom);
    add('Status', statusLabel(classifyStatus(summary)));
    var latlon = summaryLatLon(summary);
    if (latlon) {
      add('Location', pyFixed(latlon.lat, 5) + ' N, ' +
        pyFixed(Math.abs(latlon.lon), 5) + ' W');
    }
    var depth = summaryNum(summary.total_depth_m), safe = summaryNum(summary.safe_yield_m3_per_h);
    var cost = summaryNum(summary.cost_per_meter_usd);
    add('Total depth', depth ? pyFixed(depth, 1) + ' m' : null);
    add('Safe yield', safe ? pyFixed(safe, 2) + ' m3/h' : null);
    var verdictRead = summaryVerdictState(summary);
    add('Water quality', verdictRead[0]
      ? VERDICT_LONG[verdictRead[0]] +
        (verdictRead[1] ? ' (read from an older project file)' : '')
      : null);
    add('Cost per metre', cost ? '$' + pyFixed(cost, 0) : null);
    return rows;
  }

  /**
   * @param {Rec} summary a project summary
   * @returns {string}
   */
  function portfolioOnePager(summary) {
    var title = portfolioSiteLabel(summary);
    var header = 'SITE BRIEF - ' + title;
    var lines = [header, new Array(header.length + 1).join('='), ''];
    portfolioSiteDetail(summary).forEach(function (row) {
      var label = row[0] + ':';
      while (label.length < 16) label += ' ';
      lines.push(label + row[1]);
    });
    lines.push('', 'Generated by the Groundwater Investigation Toolkit.');
    return lines.join('\n');
  }

  /** @param {Rec[]|null} summaries project summaries */
  function portfolioStats(summaries) {
    var list = summaries || [];
    var drilled = list.filter(function (s) { return s.total_depth_m; });
    /* successes are counted over the same population the rate divides by, so
     * the rate can never exceed 100%: a summary classified "successful" but
     * carrying no depth is not a drilled hole */
    var successful = drilled.filter(function (s) {
      return classifyStatus(s) === 'successful';
    }).length;
    /* a hand-edited "52 m" is a blank cell and a count, not NaN in a mean */
    var num = summaryNum;
    var yields = list.map(function (s) { return num(s.safe_yield_m3_per_h); })
      .filter(function (v) { return v; });
    var costs = list.map(function (s) { return num(s.cost_per_meter_usd); })
      .filter(function (v) { return v; });
    var unreadable = 0;
    list.forEach(function (s) {
      ['total_depth_m', 'safe_yield_m3_per_h', 'cost_per_meter_usd'].forEach(function (key) {
        if (s[key] !== null && s[key] !== undefined && s[key] !== '' && num(s[key]) === null) {
          unreadable += 1;
        }
      });
    });
    var unrecognised = list.filter(function (s) {
      return s.status && classifyStatus(s) === 'other';
    }).length;
    /* There is deliberately no single "water pass rate". The old one counted
     * an aesthetic exceedance as safe AND carried national-standard failures
     * inside the aesthetic bucket, so a portfolio breaching the national
     * standard everywhere still showed 100% passing. Three rates replace it,
     * reported separately so nobody can read one of them as all three. */
    /* worst first, then the unreadable bucket - the same key order the
     * Python side emits, so the two serialise identically */
    var counts = {};
    VERDICT_ORDER.forEach(function (state) { counts[state] = 0; });
    counts.unknown = 0;
    var assessed = 0;
    list.forEach(function (s) {
      if (!s.water_verdict) return;
      assessed += 1;
      var state = summaryVerdictState(s)[0];
      counts[state && own(counts, state) ? state : 'unknown'] += 1;
    });
    function rate(total) {
      return assessed ? total / assessed * 100.0 : null;
    }
    function mean(values) {
      return values.length
        ? values.reduce(function (a, b) { return a + b; }, 0) / values.length : null;
    }
    return {
      n_projects: list.length,
      n_drilled: drilled.length,
      n_values_unreadable: unreadable,
      n_successful: successful,
      n_status_unrecognised: unrecognised,
      success_rate: drilled.length ? successful / drilled.length * 100.0 : null,
      mean_safe_yield_m3_per_h: mean(yields),
      mean_cost_per_meter_usd: mean(costs),
      n_wq_assessed: assessed,
      wq_counts: counts,
      /* meets every health AND national limit; aesthetic reservations only */
      wq_compliant_rate: rate(counts.pass + counts.aesthetic),
      wq_fail_rate: rate(counts.health_fail + counts.national_fail),
      wq_unproven_rate: rate(counts.indeterminate + counts.unknown),
    };
  }

  Object.assign(C, {
    STATUS_COLORS: STATUS_COLORS, STATUS_LABELS: STATUS_LABELS,
    statusLabel: statusLabel, statusColor: statusColor,
    classifyStatusText: classifyStatusText, normaliseStatus: normaliseStatus,
    summaryVerdictState: summaryVerdictState, VERDICT_SCHEMA: VERDICT_SCHEMA,
    classifyStatus: classifyStatus, summaryLatLon: summaryLatLon,
    summaryHoldsDegrees: summaryHoldsDegrees,
    portfolioRows: portfolioRows, portfolioPoints: portfolioPoints,
    portfolioSiteLabel: portfolioSiteLabel,
    portfolioSiteDetail: portfolioSiteDetail,
    portfolioOnePager: portfolioOnePager, portfolioStats: portfolioStats,
  });

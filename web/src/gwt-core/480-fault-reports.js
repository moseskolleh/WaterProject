
  /* ===================================================================
   * Reports from the plate and by SMS - a port of groundwater/fault_reports.py
   * (PLAN.md 7.1)
   *
   * What the people who pump a borehole say about it, from the report page a
   * plate's QR code opens, by SMS (BH <identifier> <WORD> [note]), or from
   * the file of reports a phone exports, made into registry records. Every
   * report is accepted, held or refused, with the reason. The identifier is
   * checked by validateAssetId, the registry's own check, so a mistyped one
   * is refused, and one it reads with a note is held for a person to
   * confirm when it comes by SMS, since nobody reads the note as an SMS is
   * typed. Nothing here reads the clock: a report's day is the person's, the
   * gateway's or the file's, or the day the person importing gives. The
   * gateway adapter, which is optional and not built, is receiveMessages.
   * =================================================================== */

  /* what a report can say, in the order the page offers it, and the
   * registry event each is recorded as */
  var REPORT_CHOICES = ['working', 'broken', 'slow', 'taste'];
  var REPORT_KINDS = { working: 'reported_working', broken: 'failure',
    slow: 'reported_slow', taste: 'quality_complaint' };
  var REPORTS_FORMAT = 'gwt-borehole-reports';
  var REPORTS_VERSION = 1;

  /* the blanks trimField takes off a field's ends separate a message's
   * words, the same in both engines; with commas and semicolons they
   * separate the time received, the sender and the message on a line */
  var REPORT_BLANKS = new RegExp('[' + TRIMMED + ']+');
  var REPORT_BREAKS = new RegExp('[' + TRIMMED + ',;]+');
  var REPORT_BH = new RegExp('(?:^|[' + TRIMMED + ',;])BH(?=[' + TRIMMED + ']|$)', 'i');
  var REPORT_ISO_TIME = /^[0-9]{4}-[0-9]{2}-[0-9]{2}(?:T[0-9]{1,2}:[0-9]{2}(?::[0-9]{2}(?:\.[0-9]+)?)?(?:Z|[+-][0-9]{2}:?[0-9]{2})?)?$/;
  var REPORT_CLOCK = /^[0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?$/;
  var REPORT_OTHER_DAY = /^[0-9]{1,4}[/.-][0-9]{1,2}[/.-][0-9]{1,4}$/;
  var REPORT_DAY_FIRST = /^([0-9]{4}-[0-9]{2}-[0-9]{2})(?:[T ]|$)/;

  /* The registry's own check of an identifier, validateAssetId, called
   * through C as fault_reports.py calls registry.validate_asset_id through
   * its module: whatever that check reads with a note rather than plainly
   * is held when it comes by SMS, and a test can stand in for such a check. */
  function checkReportedId(typed) {
    return C.validateAssetId(typed);
  }

  /* a field of a report, trimmed, or blank when it is not text */
  function reportText(value) {
    return typeof value === 'string' ? trimField(value) : '';
  }

  function asciiUpper(text) {
    return text.replace(/[a-z]/g, function (c) { return c.toUpperCase(); });
  }

  /* the SMS words, "WORKING, BROKEN, ... or BAD" */
  function reportWords() {
    var words = Object.keys(phraseTable('fault_reports.sms_words'));
    return words.slice(0, -1).join(', ') + ' or ' + words[words.length - 1];
  }

  /* a report with every field, in the order both engines write them */
  function reportShape(fields) {
    return Object.assign({ status: 'refused', reason: '', asset_id: '', typed: '',
      choice: '', kind: '', when: '', note: '', by: '', photo: '', photo_provenance: null,
      line: null, text: '', received: '', sender: '' }, fields);
  }

  /** A report as the report page makes it (fault_reports.report_record): on
   * the borehole assetId, one of the four choices, on the day when
   * (YYYY-MM-DD, the page's input), with an optional note, name and
   * photograph (a data URL) with its provenance record. Refused, with the
   * reason, when the identifier does not check (the registry's own words),
   * the choice is not one of the four or the day is not one; an identifier
   * the registry reads with a note is accepted, since the page shows the
   * note to the person at the plate.
   * @param {*} assetId
   * @param {*} choice
   * @param {*} when
   * @param {*} [note]
   * @param {*} [by]
   * @param {*} [photo]
   * @param {*} [photoProvenance]
   * @returns {Rec}
   */
  function reportRecord(assetId, choice, when, note, by, photo, photoProvenance) {
    var typed = reportText(assetId);
    var verdict = checkReportedId(typed);
    if (!verdict.ok) return reportShape({ reason: verdict.reason, typed: typed });
    var parsed = parseAssetId(typed) || '';
    if (REPORT_CHOICES.indexOf(choice) < 0) {
      return reportShape({ reason: phrase('fault_reports.no_choice'), asset_id: parsed,
        typed: typed });
    }
    var day = reportText(when);
    if (isoDay(day) === null) {
      return reportShape({ reason: day ? phrase('fault_reports.bad_day', { when: day })
        : phrase('fault_reports.no_day'), asset_id: parsed, typed: typed, choice: choice });
    }
    var picture = typeof photo === 'string' ? photo : '';
    return reportShape({ status: 'accepted', asset_id: parsed, typed: typed, choice: choice,
      kind: REPORT_KINDS[choice], when: day, note: reportText(note), by: reportText(by),
      photo: picture,
      photo_provenance: picture ? cleanPhotoProvenance(photoProvenance) : null });
  }

  /* an SMS report from message received on day ('' when there is none),
   * with what to show of the line it came from */
  function smsReport(message, day, received, sender, line, text) {
    var shown = { line: line, text: text, received: received, sender: sender };
    var words = reportText(message).split(REPORT_BLANKS).filter(Boolean);
    if (!words.length || asciiUpper(words[0]) !== 'BH') {
      return reportShape(Object.assign({
        reason: phrase('fault_reports.no_bh', { words: reportWords() }) }, shown));
    }
    if (words.length < 2) {
      return reportShape(Object.assign({
        reason: phrase('fault_reports.no_identifier', { words: reportWords() }) }, shown));
    }
    var typed = words[1];
    if (words.length < 3) {
      return reportShape(Object.assign({
        reason: phrase('fault_reports.no_word', { words: reportWords() }), typed: typed },
      shown));
    }
    var verdict = checkReportedId(typed);
    if (!verdict.ok) return reportShape(Object.assign({ reason: verdict.reason, typed: typed }, shown));
    var parsed = parseAssetId(typed) || '';
    var table = phraseTable('fault_reports.sms_words');
    var key = asciiUpper(words[2]);
    if (!own(table, key)) {
      return reportShape(Object.assign({
        reason: phrase('fault_reports.unknown_word', { word: words[2], words: reportWords() }),
        asset_id: parsed, typed: typed }, shown));
    }
    var choice = table[key];
    var found = { asset_id: parsed, typed: typed, choice: choice };
    if (!day) {
      return reportShape(Object.assign({ reason: phrase('fault_reports.no_date') }, found, shown));
    }
    if (isoDay(day) === null) {
      return reportShape(Object.assign({ reason: phrase('fault_reports.bad_date', { date: day }) },
        found, shown));
    }
    var by = sender ? phrase('fault_reports.sms_by', { sender: sender })
      : phrase('fault_reports.sms_by_unknown');
    var fields = Object.assign({}, found, { kind: REPORT_KINDS[choice], when: day,
      note: words.slice(3).join(' '), by: by }, shown);
    if (verdict.reason) {
      /* read, but with a note the registry shows to whoever types the
       * identifier; an SMS has nobody to show it to as it is typed */
      return reportShape(Object.assign({ status: 'held',
        reason: phrase('fault_reports.held', { note: verdict.reason }) }, fields));
    }
    return reportShape(Object.assign({ status: 'accepted' }, fields));
  }

  /* the day a report was received on: the day the time received begins
   * with, else the day given for messages that carry none */
  function reportDayOf(received, receivedOn) {
    if (received) {
      var match = REPORT_DAY_FIRST.exec(received);
      return match ? match[1] : received;
    }
    return reportText(receivedOn);
  }

  /** One SMS, BH <identifier> <WORD> [note], as a report (fault_reports.parse_sms).
   * @param {*} text the message
   * @param {*} [received] the time it was received as the gateway writes it,
   *   read only when it begins with a day written YYYY-MM-DD
   * @param {*} [sender] who sent it, kept as the report's "by"
   * @param {*} [receivedOn] the day for a message with no time received
   * @returns {Rec}
   */
  function parseSms(text, received, sender, receivedOn) {
    var stamp = reportText(received), who = reportText(sender);
    return smsReport(text, reportDayOf(stamp, receivedOn), stamp, who, null, reportText(text));
  }

  /** The interface of an SMS gateway adapter, which is optional
   * (fault_reports.receive_messages): what a gateway received, in order,
   * each with its text and, where the gateway gives them, the time it was
   * received and the sender (or the text alone), as reports numbered from 1.
   * Nothing is sent back and nothing is merged.
   * @param {*} messages
   * @param {*} [receivedOn] the day for messages with no time received
   * @returns {Rec[]}
   */
  function receiveMessages(messages, receivedOn) {
    return (Array.isArray(messages) ? messages : []).map(function (message, i) {
      var m = typeof message === 'string' ? { text: message } : (isRecord(message) ? message : {});
      var stamp = reportText(m.received), who = reportText(m.sender);
      var text = reportText(m.text);
      return smsReport(text, reportDayOf(stamp, receivedOn), stamp, who, i + 1, text);
    });
  }

  /** A plain-text file of SMS messages, one a line, as reports
   * (fault_reports.read_sms_lines). Before BH a line may carry the time
   * received (a day written YYYY-MM-DD, alone or with a time after a T,
   * then perhaps a time of day) and the sender, separated by blanks, commas
   * or semicolons; whatever else is there is the sender. A day written any
   * other way, or two days, is refused; blank lines are skipped.
   * @param {*} text
   * @param {*} [receivedOn] the day for lines that carry none
   * @returns {Rec[]}
   */
  function readSmsLines(text, receivedOn) {
    var out = [];
    var raw = typeof text === 'string' ? text : '';
    raw.split(/\r\n|\r|\n/).forEach(function (line, i) {
      var number = i + 1;
      var shown = trimField(line);
      if (!shown) return;
      var found = REPORT_BH.exec(shown);
      if (!found) {
        out.push(reportShape({ reason: phrase('fault_reports.no_bh', { words: reportWords() }),
          line: number, text: shown }));
        return;
      }
      var start = found.index + found[0].length - 2;
      var days = [], clock = [], sender = [];
      var tokens = shown.slice(0, start).split(REPORT_BREAKS);
      for (var t = 0; t < tokens.length; t++) {
        var token = tokens[t];
        if (!token) continue;
        if (REPORT_ISO_TIME.test(token)) days.push(token);
        else if (REPORT_CLOCK.test(token)) clock.push(token);
        else if (REPORT_OTHER_DAY.test(token)) {
          out.push(reportShape({ reason: phrase('fault_reports.bad_date', { date: token }),
            line: number, text: shown }));
          return;
        } else sender.push(token);
      }
      var stamp = days.concat(clock).join(' ');
      var who = sender.join(' ');
      if (days.length > 1) {
        out.push(reportShape({ reason: phrase('fault_reports.two_dates',
          { first: days[0], second: days[1] }),
        line: number, text: shown, received: stamp, sender: who }));
        return;
      }
      var day = days.length ? days[0].slice(0, 10) : reportText(receivedOn);
      out.push(smsReport(shown.slice(start), day, stamp, who, number, shown));
    });
    return out;
  }

  /** A held report, confirmed by a person: the same report, accepted
   * (fault_reports.confirm_report). Anything else is returned as it is.
   * @param {*} record
   * @returns {*}
   */
  function confirmReport(record) {
    if (!isRecord(record) || record.status !== 'held') return record;
    return Object.assign({}, record, { status: 'accepted', reason: '' });
  }

  /** The registry event an accepted report is recorded as.
   * @param {Rec} record
   * @returns {Rec}
   */
  function reportEvent(record) {
    /* read as the registry reads any saved event (coerceEvent), so a record
     * from a hand-edited queue or file becomes the same event in both engines */
    return /** @type {Rec} */ (coerceEvent({ when: record.when, kind: record.kind,
      note: record.note, by: record.by, photo: record.photo,
      photo_provenance: record.photo_provenance }));
  }

  /** The accepted records merged into the boreholes they name
   * (fault_reports.merge_reports): each asset with the reports naming it
   * merged by the registry's rule, the rest as they were; added counts the
   * records new to a history, already those it held, and unmatched are the
   * accepted reports that name none of the boreholes.
   * @param {*} assets registry records
   * @param {*} records reports
   * @returns {{assets: Rec[], added: number, already: number, unmatched: Rec[]}}
   */
  function mergeReports(assets, records) {
    var accepted = (Array.isArray(records) ? records : []).filter(function (r) {
      return isRecord(r) && r.status === 'accepted';
    });
    /** @type {Object<string, boolean>} */
    var matched = {};
    var out = [], added = 0, already = 0;
    (Array.isArray(assets) ? assets : []).forEach(function (raw) {
      var asset = assetFromDict(raw);
      if (!asset) return;
      var assetId = asset.asset_id;
      /** @type {number[]} */
      var mine = [];
      accepted.forEach(function (r, i) { if (r.asset_id === assetId) mine.push(i); });
      if (!mine.length) { out.push(asset); return; }
      /** @type {Object<string, boolean>} */
      var known = {};
      mergeEvents(assetId, asset.events).forEach(function (e) { known[e.event_id] = true; });
      var events = mine.map(function (i) { return reportEvent(accepted[i]); });
      /** @type {Object<string, boolean>} */
      var ids = {};
      events.forEach(function (e) {
        ids[identifiedFor(/** @type {Rec} */ (coerceEvent(e)), assetId).event_id] = true;
      });
      Object.keys(ids).forEach(function (id) { if (own(known, id)) already += 1; else added += 1; });
      mine.forEach(function (i) { matched[i] = true; });
      out.push(Object.assign({}, asset, {
        events: mergeEvents(asset.asset_id, asset.events, events) }));
    });
    return { assets: out, added: added, already: already,
      unmatched: accepted.filter(function (r, i) { return !own(matched, String(i)); }) };
  }

  /** The accepted records as the file a phone exports (fault_reports.reports_file).
   * @param {*} records
   * @returns {Rec}
   */
  function reportsFile(records) {
    var out = [];
    (Array.isArray(records) ? records : []).forEach(function (record) {
      if (!isRecord(record) || record.status !== 'accepted') return;
      /* each field as text, so a hand-edited record is written the same by
       * both engines; read back, every report is checked again anyway */
      /** @type {Rec} */
      var entry = { asset_id: reportText(record.asset_id), choice: reportText(record.choice),
        when: reportText(record.when), note: reportText(record.note), by: reportText(record.by) };
      if (typeof record.photo === 'string' && record.photo) {
        entry.photo = record.photo;
        var provenance = cleanPhotoProvenance(record.photo_provenance);
        if (provenance) entry.photo_provenance = provenance;
      }
      out.push(entry);
    });
    return { format: REPORTS_FORMAT, version: REPORTS_VERSION, reports: out };
  }

  /** The reports in a file reportsFile wrote, each checked again as the page
   * checks one, numbered from 1 in line (fault_reports.read_reports_file). A
   * file not of this format and version is refused whole.
   * @param {*} payload the file, parsed
   * @returns {Rec[]}
   */
  function readReportsFile(payload) {
    if (!isRecord(payload) || payload.format !== REPORTS_FORMAT ||
        payload.version !== REPORTS_VERSION || !Array.isArray(payload.reports)) {
      throw new Error(phrase('fault_reports.file_refused'));
    }
    return payload.reports.map(function (entry, i) {
      var e = isRecord(entry) ? entry : {};
      return Object.assign(reportRecord(reportText(e.asset_id), e.choice, e.when, e.note, e.by,
        e.photo, e.photo_provenance), { line: i + 1 });
    });
  }

  /** The header of the table of an import, in both apps.
   * @returns {string[]}
   */
  function reportHeader() {
    var columns = phraseTable('fault_reports.columns');
    return Object.keys(columns).map(function (k) { return columns[k]; });
  }

  /** One row of the table of an import a report: its line, when it was
   * received, who sent it, the borehole as given, what it says, what became
   * of it and why (fault_reports.report_rows).
   * @param {*} records
   * @returns {string[][]}
   */
  function reportRows(records) {
    var says = phraseTable('fault_reports.choices');
    var outcome = phraseTable('fault_reports.outcome');
    return (Array.isArray(records) ? records : []).filter(function (r) {
      return isRecord(r) && typeof r.status === 'string' && own(outcome, r.status);
    }).map(function (r) {
      return [r.line === null || r.line === undefined ? '' : String(r.line),
        r.received || r.when || '', r.sender || '', r.asset_id || r.typed || '',
        r.choice && own(says, r.choice) ? says[r.choice] : '', outcome[r.status], r.reason || ''];
    });
  }

  /** What a report by SMS and a file of them look like, as both apps' imports
   * say it (fault_reports.sms_format).
   * @returns {string}
   */
  function smsFormat() {
    return phrase('fault_reports.sms_format', { words: reportWords() });
  }

  /** How many reports an import read and what became of them.
   * @param {*} records
   * @returns {string}
   */
  function importSummary(records) {
    var list = (Array.isArray(records) ? records : []).filter(isRecord);
    /** @param {string} status */
    function count(status) {
      return list.filter(function (r) { return r.status === status; }).length;
    }
    return phrase('fault_reports.import_summary', { n: list.length, accepted: count('accepted'),
      held: count('held'), refused: count('refused') });
  }

  Object.assign(C, {
    REPORT_CHOICES: REPORT_CHOICES, REPORT_KINDS: REPORT_KINDS,
    REPORTS_FORMAT: REPORTS_FORMAT, REPORTS_VERSION: REPORTS_VERSION,
    reportRecord: reportRecord, parseSms: parseSms, receiveMessages: receiveMessages,
    readSmsLines: readSmsLines, confirmReport: confirmReport, reportEvent: reportEvent,
    mergeReports: mergeReports, reportsFile: reportsFile, readReportsFile: readReportsFile,
    reportHeader: reportHeader, reportRows: reportRows, importSummary: importSummary,
    smsFormat: smsFormat
  });

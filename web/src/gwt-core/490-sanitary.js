
  /* ===================================================================
   * Sanitary inspection - a port of groundwater/sanitary.py (PLAN.md 7.5)
   *
   * WHO's ten-question form for a tubewell with a handpump, scored as the
   * number of risks present, and the E. coli count of the water quality
   * assessment graded A to E, read together in a risk-to-health matrix into
   * one statement. The form, the bands, the grades and the matrix are data
   * (GWT.data.sanitary, from sanitary_inspection.csv and
   * sanitary_risk.yaml); the words are in text/sanitary.yaml. A question
   * left unanswered is not a no, a side that is unknown gives no priority,
   * and a side known only as a range is taken at its worse end.
   * =================================================================== */

  var SANITARY_FORM = 'tubewell_handpump';
  var SANITARY_PRIORITIES = ['low', 'higher', 'urgent'];
  /* the scale the grades are written on, whatever unit the standards table
   * writes E. coli in */
  var PER_100_ML = { parameter: 'E. coli', unit: 'CFU/100 mL' };

  /** data/sanitary_inspection.csv and data/sanitary_risk.yaml as the
   * package parses them, shared: read, never changed.
   * @returns {Rec} */
  function sanitaryTables() {
    var tables = (GWT.data || {}).sanitary;
    if (!tables) {
      throw new Error('gwt-data.js is not loaded, or is stale: it carries the ' +
        'sanitary inspection form (src/groundwater/data/sanitary_*)');
    }
    return tables;
  }

  /** @param {string} form */
  function sanitaryForm(form) {
    var forms = sanitaryTables().forms;
    return own(forms, form) ? forms[form] : null;
  }

  /** The form's questions, in order.
   * @param {string} [form]
   * @returns {string[]} */
  function formQuestions(form) {
    var spec = sanitaryForm(form || SANITARY_FORM);
    return spec ? spec.questions.slice() : [];
  }

  /** The key of the band a score falls in.
   * @param {number} score
   * @param {string} [form]
   * @returns {string} */
  function scoreBand(score, form) {
    var name = form || SANITARY_FORM;
    var spec = sanitaryForm(name);
    if (!spec) throw new Error('no sanitary inspection form ' + JSON.stringify(name));
    for (var i = 0; i < spec.bands.length; i++) {
      if (spec.bands[i].min <= score && score <= spec.bands[i].max) return spec.bands[i].key;
    }
    throw new Error(score + ' is not a score of the ' + name + ' form');
  }

  /** What a form's answers score, or null when they do not fit it. An
   * unanswered question may be a yes, so an incomplete form scores a range.
   * @param {*} answers
   * @param {string} [form]
   * @returns {Rec|null} */
  function scoreAnswers(answers, form) {
    var name = form === undefined ? SANITARY_FORM : form;
    var spec = sanitaryForm(name);
    var text = cleanAnswers(answers);
    if (!spec || text.length !== spec.questions.length) return null;
    var n = text.length;
    var yes = text.split('Y').length - 1;
    var answered = n - (text.split('-').length - 1);
    var low = yes, high = yes + (n - answered);
    return { form: name, n: n, answered: answered, yes: yes, low: low, high: high,
      band_low: scoreBand(low, name), band_high: scoreBand(high, name),
      complete: answered === n };
  }

  /** Number, question and answer for each question, for a table.
   * @param {*} answers
   * @param {string} [form]
   * @returns {string[][]} */
  function formRows(answers, form) {
    var words = phraseTable('sanitary.answer');
    var text = cleanAnswers(answers);
    return formQuestions(form).map(function (question, i) {
      return [String(i + 1), question, words[i < text.length ? text.charAt(i) : '-']];
    });
  }

  /** A sanitary inspection, as the registry records it.
   * @param {string} when
   * @param {*} answers
   * @param {string} [by]
   * @param {string} [note]
   * @param {string} [form]
   * @returns {Rec} */
  function inspectionEvent(when, answers, by, note, form) {
    return { when: trimField(when), kind: 'inspection', note: note || '',
      by: by || '', photo: '', form: form || SANITARY_FORM,
      answers: cleanAnswers(answers) };
  }

  /** The grade of a count per 100 mL: A for none, then B to E.
   * @param {number} count
   * @returns {string} */
  function ecoliGrade(count) {
    var grades = sanitaryTables().grades;
    for (var i = 0; i < grades.length; i++) {
      if (grades[i].max === null || count <= grades[i].max) return grades[i].grade;
    }
    throw new Error('the last grade is open above');
  }

  /** The grades a count of more than bound (or at least it) may be in.
   * @param {number} bound
   * @param {boolean} [inclusive]
   * @returns {string[]} */
  function ecoliGradesAbove(bound, inclusive) {
    var grades = sanitaryTables().grades;
    for (var i = 0; i < grades.length; i++) {
      var top = grades[i].max;
      if (top === null || bound < top || (inclusive && bound <= top)) {
        return [grades[i].grade, grades[grades.length - 1].grade];
      }
    }
    throw new Error('the last grade is open above');
  }

  function per100ml(value, unit) {
    return toGuidelineUnit(Number(value), unit, PER_100_ML).value;
  }

  /* an assessment's remark, made to close a sentence the statement ends: a
   * remark may or may not end in a full stop of its own, and the statement
   * adds one, so the remark's is taken off with any blanks after it - the
   * same characters as sanitary._reason takes */
  function ecoliReason(remark) {
    return String(remark || '').replace(/[ \t\n\r\f\v.]+$/, '');
  }

  /* what one E. coli row of an assessment says, on the grades' scale */
  function ecoliGraded(row) {
    /** @type {Rec} */
    var out = { parameter: row.parameter, kind: 'ungraded', count: null,
      bound: null, inclusive: false, grade_low: null, grade_high: null,
      reason: ecoliReason(row.remark), unit: row.unit };
    if (!row.evaluable || row.status === 'indeterminate') return out;
    if (row.status === 'below_detection') {
      return Object.assign(out, { kind: 'none_found', count: 0, grade_low: 'A',
        grade_high: 'A', reason: '' });
    }
    if (row.value !== null && row.value !== undefined) {
      var count = per100ml(row.value, row.unit);
      if (count === null) return Object.assign(out, { kind: 'unit', reason: '' });
      var grade = ecoliGrade(count);
      return Object.assign(out, { kind: 'counted', count: count, grade_low: grade,
        grade_high: grade, reason: '' });
    }
    if (row.greater_than !== null && row.greater_than !== undefined) {
      var bound = per100ml(row.greater_than, row.unit);
      if (bound === null) return Object.assign(out, { kind: 'unit', reason: '' });
      var inclusive = !!row.greater_than_inclusive;
      var span = ecoliGradesAbove(bound, inclusive);
      return Object.assign(out, { kind: bound === 0 && !inclusive ? 'detected' : 'bound',
        bound: bound, inclusive: inclusive, grade_low: span[0], grade_high: span[1],
        reason: '' });
    }
    return out;
  }

  /** The E. coli side of the risk from a water quality assessment: null
   * with no assessment; else the sample's date as written and the worst row
   * graded of those naming E. coli or an alias, or with none graded the
   * first the assessment could not grade.
   * @param {QualityAssessment|null} [assessment]
   * @returns {Rec|null} */
  function microbiology(assessment) {
    if (!assessment) return null;
    var sample = assessment.sample || {};
    var when = trimField(sample.sample_date || '');
    var order = sanitaryTables().grades.map(function (g) { return g.grade; });
    /** @type {Rec[]} */
    var graded = [];
    /** @type {Rec[]} */
    var ungraded = [];
    (assessment.rows || []).forEach(function (row) {
      if (normaliseParameter(row.parameter) !== 'e. coli' || row.status === 'not_measured') return;
      var result = ecoliGraded(row);
      (result.grade_low !== null ? graded : ungraded).push(result);
    });
    var best;
    if (graded.length) {
      /* the first of equals, as Python's max keeps it */
      best = graded[0];
      graded.forEach(function (r) {
        var a = [order.indexOf(r.grade_high), order.indexOf(r.grade_low)];
        var b = [order.indexOf(best.grade_high), order.indexOf(best.grade_low)];
        if (a[0] > b[0] || (a[0] === b[0] && a[1] > b[1])) best = r;
      });
    } else if (ungraded.length) {
      best = ungraded[0];
    } else {
      best = { parameter: '', kind: 'missing', count: null, bound: null,
        inclusive: false, grade_low: null, grade_high: null, reason: '', unit: '' };
    }
    return Object.assign({ date: when }, best);
  }

  /** The inspection the risk statement rests on: the latest whose form
   * scores, dated no later than today (of several that day, the one showing
   * the most risk); the latest unscored one after it; and, with none that
   * scores, the latest form recorded that does not.
   * @param {Rec[]} events merged, in the registry's order
   * @param {string} today an ISO day
   * @returns {Rec} */
  function latestInspection(events, today) {
    var read = isoDay(today);
    if (read === null) {
      throw new Error("the risk statement needs today's date, as YYYY-MM-DD");
    }
    var todayDay = read;
    /** @type {Rec[]} */
    var inspections = [];
    /* forms whose date cannot be read: not read, and the statement says so */
    var undated = 0;
    (events || []).forEach(function (event) {
      if (event.kind !== 'inspection') return;
      var day = isoDay(event.when);
      if (day === null) {
        if (event.form || event.answers) undated += 1;
        return;
      }
      if (day > todayDay) return;
      var score = event.form || event.answers ? scoreAnswers(event.answers, event.form || '') : null;
      inspections.push({ day: day, event: event, score: score });
    });
    var scored = inspections.filter(function (i) { return i.score && i.score.answered; });
    var unscored = inspections.filter(function (i) { return !(i.score && i.score.answered); });
    /* the first of the best, as Python's max keeps it
     * @param {Rec[]} list
     * @param {function(Rec, Rec): boolean} better */
    function first(list, better) {
      var top = list[0];
      list.forEach(function (i) { if (better(i, top)) top = i; });
      return top;
    }
    var pick = null, sameDay = 0, later = null, blank = null;
    if (scored.length) {
      var last = Math.max.apply(null, scored.map(function (i) { return i.day; }));
      var onDay = scored.filter(function (i) { return i.day === last; });
      sameDay = onDay.length;
      pick = first(onDay, function (a, b) {
        return a.score.high > b.score.high ||
          (a.score.high === b.score.high && a.score.low > b.score.low);
      });
      var after = unscored.filter(function (i) { return i.day > last; });
      if (after.length) later = first(after, function (a, b) { return a.day > b.day; }).event;
    } else {
      var forms = unscored.filter(function (i) { return i.event.form || i.event.answers; });
      if (forms.length) blank = first(forms, function (a, b) { return a.day > b.day; });
    }
    return {
      event: pick ? pick.event : null, score: pick ? pick.score : null,
      same_day: sameDay, later: later,
      unscored: blank ? blank.event : null,
      unscored_fits: blank ? blank.score !== null : false,
      undated: undated,
    };
  }

  /* the latest water sample the history records, dated no later than
   * todayDay, with its day; of several that day, the first in the
   * registry's order, as sanitary._latest_sample keeps it */
  function latestSampleEvent(events, todayDay) {
    /** @type {{event: Rec, day: number}|null} */
    var pick = null;
    var list = events || [];
    for (var i = 0; i < list.length; i++) {
      var day = list[i].kind === 'water_sample' ? isoDay(list[i].when) : null;
      if (day !== null && day <= todayDay && (pick === null || day > pick.day)) {
        pick = { event: list[i], day: day };
      }
    }
    return pick;
  }

  function sanitaryWhen(event) {
    var by = trimField(event.by);
    return by ? phrase('sanitary.dated_by', { date: event.when, by: by }) : event.when;
  }

  function sanitarySpan(low, high, table) {
    return low === high ? table[low]
      : phrase('sanitary.span', { low: table[low], high: table[high] });
  }

  /** The borehole's sanitary risk on today, as one statement: the latest
   * scored inspection, the E. coli grade of the assessment's sample, and
   * the two read together, with the action priority to act on (null until
   * both sides are known well enough to read one). sample_event is the
   * latest water sample the history records, which the statement names
   * when no analysis is loaded or when it is later than the one read.
   * @param {Rec} asset a registry asset; its events are read
   * @param {string} today an ISO day; records dated after it are not read
   * @param {QualityAssessment|null} [assessment] the latest sample's
   * @returns {Rec} */
  function sanitaryRisk(asset, today, assessment) {
    var events = mergeEvents((asset && asset.asset_id) || '', (asset && asset.events) || []);
    var found = latestInspection(events, today);
    var sampled = latestSampleEvent(events, /** @type {number} */ (isoDay(today)));
    var micro = microbiology(assessment || null);
    var grades = sanitaryTables().grades.map(function (g) { return g.grade; });
    var bandWords = phraseTable('sanitary.band');
    var sentences = [];

    var event = found.event, score = found.score;
    var form = event ? event.form : SANITARY_FORM;
    if (score && event) {
      if (score.complete) {
        sentences.push(phrase('sanitary.inspection_complete', { when: sanitaryWhen(event),
          yes: score.yes, n: score.n, band: bandWords[score.band_low] }));
      } else {
        sentences.push(phrase('sanitary.inspection_incomplete', {
          when: sanitaryWhen(event), answered: score.answered, n: score.n,
          yes: score.yes, low: score.low, high: score.high,
          band: sanitarySpan(score.band_low, score.band_high, bandWords) }));
      }
      if (found.same_day > 1) {
        sentences.push(phrase('sanitary.inspection_several',
          { count: found.same_day, date: event.when }));
      }
      if (found.later) {
        sentences.push(phrase('sanitary.inspection_later', { when: sanitaryWhen(found.later) }));
      }
    } else if (found.unscored) {
      var key = found.unscored_fits ? 'sanitary.inspection_blank'
        : 'sanitary.inspection_unreadable';
      sentences.push(phrase(key, { when: sanitaryWhen(found.unscored) }));
    } else if (found.undated) {
      sentences.push(phrase('sanitary.inspection_undated_only', { count: found.undated }));
    } else {
      sentences.push(phrase('sanitary.inspection_none'));
    }
    if (found.undated && (score || found.unscored)) {
      sentences.push(phrase('sanitary.inspection_undated', { count: found.undated }));
    }

    var gradeWords = phraseTable('sanitary.grade');
    if (!micro) {
      if (sampled) {
        sentences.push(phrase('sanitary.sample_not_loaded', { when: sanitaryWhen(sampled.event) }));
      } else {
        sentences.push(phrase('sanitary.no_sample'));
      }
    } else {
      var dated = micro.date || phrase('sanitary.undated');
      var kind = micro.kind;
      if (kind === 'missing') {
        sentences.push(phrase('sanitary.ecoli_missing', { date: dated }));
      } else if (kind === 'counted') {
        sentences.push(phrase('sanitary.ecoli_counted', { parameter: micro.parameter,
          date: dated, count: micro.count, grade: micro.grade_low,
          words: gradeWords[micro.grade_low] }));
      } else if (kind === 'none_found') {
        sentences.push(phrase('sanitary.ecoli_none_found', { parameter: micro.parameter,
          date: dated, words: gradeWords.A }));
      } else if (kind === 'bound' || kind === 'detected') {
        /** @type {Record<string, string>} */
        var letters = {};
        grades.forEach(function (g) { letters[g] = g; });
        var span = sanitarySpan(micro.grade_low, micro.grade_high, letters);
        if (kind === 'detected') {
          sentences.push(phrase('sanitary.ecoli_detected', { parameter: micro.parameter,
            date: dated, grades: span }));
        } else {
          var boundKey = micro.inclusive ? 'sanitary.ecoli_at_least' : 'sanitary.ecoli_over';
          sentences.push(phrase(boundKey, { parameter: micro.parameter, date: dated,
            bound: micro.bound, grades: span }));
        }
      } else if (kind === 'unit') {
        sentences.push(phrase('sanitary.ecoli_unit', { parameter: micro.parameter,
          date: dated, unit: micro.unit }));
      } else if (micro.reason) {
        sentences.push(phrase('sanitary.ecoli_ungraded', { parameter: micro.parameter,
          date: dated, reason: micro.reason }));
      } else {
        sentences.push(phrase('sanitary.ecoli_ungraded_bare', { parameter: micro.parameter,
          date: dated }));
      }
      /* a later sample on record is named, so the statement does not pass
       * off an older analysis as the borehole's latest word */
      var readOn = isoDay(micro.date);
      if (sampled && readOn !== null && sampled.day > readOn) {
        sentences.push(phrase('sanitary.sample_later', { when: sanitaryWhen(sampled.event) }));
      }
    }

    /* the cells the two sides allow: a side not known allows every one */
    var spec = sanitaryForm(form) || /** @type {Rec} */ (sanitaryForm(SANITARY_FORM));
    var n = spec.questions.length;
    var scores = [];
    for (var s = score ? score.low : 0; s <= (score ? score.high : n); s++) scores.push(s);
    var knownGrade = !!micro && micro.grade_low !== null;
    var rows = knownGrade && micro
      ? grades.slice(grades.indexOf(micro.grade_low), grades.indexOf(micro.grade_high) + 1)
      : grades;
    var cells = [];
    rows.forEach(function (g) {
      scores.forEach(function (sc) { cells.push(spec.matrix[g][sc]); });
    });
    var rank = function (p) { return SANITARY_PRIORITIES.indexOf(p); };
    var low = cells[0], high = cells[0];
    cells.forEach(function (c) {
      if (rank(c) < rank(low)) low = c;
      if (rank(c) > rank(high)) high = c;
    });
    var priorityWords = phraseTable('sanitary.priority');
    var bothKnown = !!score && knownGrade;
    var action;
    if (low === high) {
      action = low;
      sentences.push(phrase('sanitary.together', { priority: priorityWords[low] }));
    } else if (bothKnown) {
      action = high;
      var level = phraseTable('sanitary.priority_level');
      sentences.push(phrase('sanitary.together_range', { low: level[low],
        high: level[high], priority: priorityWords[high] }));
    } else {
      action = null;
      if (low === SANITARY_PRIORITIES[0]) {
        sentences.push(phrase('sanitary.together_unknown'));
      } else {
        sentences.push(phrase('sanitary.together_floor', { priority: priorityWords[low] }));
      }
    }

    var verdict = assessment ? assessment.verdict_state : null;
    if (verdict) {
      sentences.push(phrase('sanitary.verdict', { verdict: VERDICT_LONG[verdict] }));
    }

    return {
      inspection: event ? { when: event.when, by: event.by, form: event.form,
        answers: event.answers, event_id: event.event_id,
        label: sanitaryWhen(event) } : null,
      score: score,
      microbiology: micro,
      sample_event: sampled ? { when: sampled.event.when, by: sampled.event.by,
        event_id: sampled.event.event_id, label: sanitaryWhen(sampled.event) } : null,
      priority_low: low,
      priority_high: high,
      action: action,
      settled: low === high,
      statement: sentences.join(' '),
    };
  }

  Object.assign(C, {
    SANITARY_FORM: SANITARY_FORM, SANITARY_PRIORITIES: SANITARY_PRIORITIES,
    sanitaryTables: sanitaryTables, formQuestions: formQuestions,
    scoreBand: scoreBand, scoreAnswers: scoreAnswers, formRows: formRows,
    inspectionEvent: inspectionEvent, ecoliGrade: ecoliGrade,
    ecoliGradesAbove: ecoliGradesAbove, microbiology: microbiology,
    latestInspection: latestInspection, sanitaryRisk: sanitaryRisk
  });

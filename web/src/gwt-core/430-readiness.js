
  /* ============================================================== readiness
   * groundwater/readiness.py. Whether a project's results are complete
   * enough to certify.
   *
   * Completeness, not outcome: a borehole whose water fails the arsenic
   * guideline is perfectly certifiable, because the finding is the point of
   * the report. What is not certifiable is a borehole whose arsenic result
   * could not be read. A gate that failed bad news would teach people to
   * leave the bad news out.
   */

  var UNIT_BLOCKERS = ['time_unit_unknown', 'discharge_unit_unknown',
    'discharge_ambiguous', 'time_reading_unreadable'];
  /* A drilling log converted from feet is among the assumptions: the depths
   * were read, but the report should say they were converted, and a bare
   * depth may have been read in feet because the rest of the sheet was. */
  var UNIT_ASSUMPTIONS = ['discharge_unit_assumed', 'unit_not_reported',
    'unit_basis_assumed', 'utm_zone_assumed', 'test_type_inferred', 'feet_converted'];

  /* The flags the drilling log reader raised with one of `codes`, the
   * reader's own lists (DRILLING_UNREADABLE, DRILLING_REFUSALS), so the gate
   * and the reader cannot drift. */
  function drillingFlags(log, codes) {
    return flagsWithCode(readinessFlags([log]), codes);
  }

  function readinessFlags(objects) {
    var out = [];
    (objects || []).forEach(function (obj) {
      if (obj && obj.flags) out = out.concat(obj.flags);
    });
    return out;
  }

  function flagsWithCode(flags, codes) {
    return flags.filter(function (f) { return codes.indexOf(f && f.code) >= 0; });
  }

  /* Crews write the GPS on one sheet and not the others, so a project can be
   * well located while the drilling log's own header block is blank. */
  function projectSite(state) {
    var candidates = [state.site];
    if (state.drilling_log) candidates.push(state.drilling_log.site);
    if (state.pump_analysis && state.pump_analysis.test) {
      candidates.push(state.pump_analysis.test.site);
    }
    if (state.wq_assessment && state.wq_assessment.sample) {
      candidates.push(state.wq_assessment.sample.site);
    }
    var merged = /** @type {Rec|null} */ (null);
    candidates.forEach(function (site) {
      if (!site) return;
      if (!merged) { merged = Object.assign({}, site); return; }
      Object.keys(site).forEach(function (key) {
        var current = /** @type {Rec} */ (merged)[key];
        if ((current === null || current === undefined || current === '') &&
            site[key] !== null && site[key] !== undefined && site[key] !== '') {
          /** @type {Rec} */ (merged)[key] = site[key];
        }
      });
    });
    return merged;
  }

  /** What each bundled example file actually contains, the same record the
   * Python engine reads. Keyed by basename: the browser bundles
   * "dr_timbo/dr_timbo_water_quality.xlsx", the Streamlit picker offers the
   * same relative path and the example script opens it straight off disk,
   * and it is one file whichever of those did it.
   * @param {Rec[]|null} [rows] the bundled table when not given
   * @returns {Record<string, Rec>}
   */
  function loadSampleProvenance(rows) {
    var source = rows || (GWT.data && GWT.data.sampleProvenance) || [];
    /** @type {Record<string, Rec>} */
    var out = {};
    source.forEach(function (row) {
      var file = String(row.file || '').trim();
      var base = /** @type {string} */ (file.split('/').pop()).toLowerCase();
      if (!base) return;
      out[base] = {
        file: file,
        kind: String(row.provenance || '').trim().toLowerCase(),
        note: String(row.note || '').trim(),
      };
    });
    return out;
  }

  /** The provenance record for one loaded source, if it is a bundled file.
   * Either key is matched, so a file is recognised however it was loaded.
   * @param {*} source a loaded source record
   * @param {Record<string, Rec>} [known] what loadSampleProvenance returns
   * @returns {Rec|null}
   */
  function sourceProvenance(source, known) {
    if (!source || typeof source !== 'object') return null;
    var table = known || loadSampleProvenance();
    var keys = ['sample', 'name'];
    for (var i = 0; i < keys.length; i += 1) {
      var value = source[keys[i]];
      if (!value) continue;
      var base = /** @type {string} */ (String(value).split('/').pop()).toLowerCase();
      if (table[base]) return table[base];
    }
    return null;
  }

  var READINESS_CHECKS = {
    /* The report describes this borehole, not a worked example.
     *
     * The toolkit ships example datasets and offers them from a picker,
     * which is right: nobody should have to have drilled a borehole to see
     * what the software does. But the documents it writes from them carry
     * the same letterhead and the same signature block as the ones it
     * writes from real work, and they leave as .docx files that get
     * forwarded and filed. So the fact travels with the document.
     *
     * Two different things fail this, and they are not equally serious: a
     * source whose readings were invented (the Dr Timbo water quality
     * workbook - no sample was ever taken), and a source picked from the
     * sample list whoever it was transcribed from (the Rokel soundings are
     * a real 2015 survey, but a report produced by clicking "load a sample"
     * is a survey of Rokel, not of the site on its cover). Both are stated
     * rather than blocked, and an override is recorded on the cover. */
    field_data: ['Field data', function (state) {
      var sources = state.sources;
      if (!sources || typeof sources !== 'object') {
        return ['met', 'No input is a bundled example file.'];
      }
      var known = loadSampleProvenance();
      var invented = [], bundled = [];
      Object.keys(sources).forEach(function (role) {
        var source = sources[role];
        var record = sourceProvenance(source, known);
        if (!record) return;
        var base = record.file.split('/').pop();
        /* Synthetic is true of the file however it was opened: nothing was
         * sampled. Being a bundled example only counts when it was picked
         * from the sample list - the marker the two apps' pickers set and
         * nothing else does - because that is a fact about the session, not
         * about the data. A script publishing the Rokel example under the
         * Rokel name is reporting exactly what it says it is. */
        var into = null;
        if (record.kind === 'synthetic') into = invented;
        else if (source && source.sample) into = bundled;
        if (into && into.indexOf(base) < 0) into.push(base);
      });
      if (invented.length) {
        return ['unmet', 'Readings that were never measured are in this ' +
          'project: ' + invented.sort().join(', ') + '. The values in ' +
          (invented.length === 1 ? 'that file were' : 'those files were') +
          ' invented to demonstrate the toolkit, so no result derived from ' +
          'them describes anything that was sampled.'];
      }
      if (bundled.length) {
        return ['unmet', 'This project is built on the bundled example data (' +
          bundled.sort().join(', ') + '), which was recorded at another ' +
          'site. The analysis is of that example, not of the borehole named ' +
          'on this report.'];
      }
      return ['met', 'No input is a bundled example file.'];
    }],
    site_located: ['Site position', function (state) {
      var site = projectSite(state);
      if (!site || site.easting === null || site.easting === undefined ||
          site.northing === null || site.northing === undefined) {
        return ['unmet', 'No GPS position is recorded on any sheet in this ' +
          'project. A borehole that cannot be found again on the ground ' +
          'cannot be certified, revisited or maintained.'];
      }
      /* Degrees typed into the UTM boxes are no position: this gate read
       * them as degrees and passed a placard whose identifier could not be
       * minted, while the Python refused them as a point near the equator.
       * Both refuse them now, in the same words. */
      var degrees = degreesInUtmBoxes(site.easting, site.northing);
      if (degrees) return ['unmet', degrees];
      /* check_site_consistency's one error: a position that converts to
       * somewhere outside the country. The site page said so and the gate
       * let the report through unstamped, where the Python holds it back. */
      var position = sitePosition(site);
      var outside = position ? outsideCountryNote(position.lat, position.lon) : '';
      if (outside) return ['unmet', outside];
      var zone = Number(site.utm_zone) || inferZoneForSierraLeone(Number(site.easting));
      return ['met', 'Position recorded: ' + Math.round(site.easting) + ' mE, ' +
        Math.round(site.northing) + ' mN (UTM ' + zone + 'N).'];
    }],
    borehole_logged: ['Drilling log', function (state) {
      var log = state.drilling_log;
      if (!log) return ['unmet', 'No drilling log has been loaded.'];
      if (!log.total_depth_m) return ['unmet', 'The drilling log records no total depth.'];
      if (!(log.intervals || []).length) {
        return ['unmet', 'The drilling log records no lithology.'];
      }
      /* A log the reader dropped a row of, or refused a strike from, is not
       * the log the crew wrote: the gate used to call it met, and "Logged to
       * 45 m" stood over a log that had lost its 5-10 m row and both water
       * strikes. */
      var refused = drillingFlags(log, DRILLING_REFUSALS);
      if (refused.length) {
        var seen = [];
        refused.forEach(function (f) { if (seen.indexOf(f.message) < 0) seen.push(f.message); });
        return ['unmet', phrase('drilling.gate_set_aside', { messages: seen.join(' ') })];
      }
      return ['met', 'Logged to ' + pyFixed(log.total_depth_m, 0) + ' m with ' +
        plural(log.intervals.length, 'lithological interval') + '.'];
    }],
    readings_usable: ['Readable units', function (state) {
      var analysis = state.pump_analysis;
      var flags = readinessFlags([analysis, state.drilling_log,
        analysis ? analysis.test : null]);
      /* and every cell the drilling log reader could not read: "every
       * reading carried a unit the toolkit could read" was said of a log
       * whose strike cells it had refused and whose rows it had skipped */
      var refused = flagsWithCode(flags, UNIT_BLOCKERS)
        .concat(drillingFlags(state.drilling_log, DRILLING_UNREADABLE));
      if (refused.length) {
        return ['unmet', refused.map(function (f) { return f.message; }).join('; ')];
      }
      return ['met', 'Every reading carried a unit the toolkit could read.'];
    }],
    pumping_measured: ['Pumping test measured', function (state) {
      var analysis = state.pump_analysis;
      if (!analysis) return ['unmet', 'No pumping test has been analysed.'];
      var test = analysis.test;
      if (test.static_water_level_m === null || test.static_water_level_m === undefined) {
        return ['unmet', 'The static water level is missing, so no drawdown ' +
          'can be computed from the test.'];
      }
      var missing = (test.steps || []).filter(function (s) {
        return s.discharge_m3_per_h === null || s.discharge_m3_per_h === undefined;
      });
      if (missing.length === (test.steps || []).length) {
        return ['unmet', 'No discharge is recorded for the test, so ' +
          'transmissivity and yield stay pending.'];
      }
      if (missing.length) {
        return ['unmet', 'Discharge is missing for ' +
          pluralNoun(missing.length, 'step') + ' ' +
          missing.map(function (s) { return s.step_number; }).join(', ') + '.'];
      }
      return ['met', plural(test.steps.length, 'step') + ' with discharge, ' +
        'static water level ' + pyFixed(test.static_water_level_m, 2) + ' m.'];
    }],
    yield_established: ['Yield established', function (state) {
      var analysis = state.pump_analysis;
      if (!analysis || !analysis.yield_recommendation) {
        return ['unmet', 'No yield recommendation has been derived.'];
      }
      var rec = analysis.yield_recommendation;
      if (rec.pending_reason) return ['unmet', rec.pending_reason];
      if (rec.safe_yield_m3_per_h === null || rec.safe_yield_m3_per_h === undefined) {
        return ['unmet', 'The safe yield could not be derived from this test.'];
      }
      /* A yield the analysis itself calls indicative is not established. The
       * gate used to certify a 30-minute test inside its casing storage on
       * the strength of the number alone. */
      if (rec.confidence === 'indicative') {
        return ['unmet', 'The safe yield of ' + yieldRangeText(rec) + ' is ' +
          'indicative, not established: ' +
          (rec.confidence_reasons || []).join('; ') + '.'];
      }
      return ['met', 'Safe yield ' + yieldRangeText(rec) + '.'];
    }],
    water_quality_panel: ['Water quality panel', function (state) {
      var a = state.wq_assessment;
      if (!a) return ['unmet', 'No water quality results have been assessed.'];
      if ((a.missing_essential || []).length) {
        return ['unmet', 'No evaluable result for ' +
          a.missing_essential.join(', ') + '.'];
      }
      return ['met', 'The health panel was run and every result was evaluable.'];
    }],
    water_quality_evaluable: ['Water quality evaluable', function (state) {
      /* The rows, not the headline: a health exceedance outranks uncertainty
       * in the verdict but does not make an unreadable result readable. */
      var a = state.wq_assessment;
      if (!a) return ['unmet', 'No water quality results have been assessed.'];
      var ungraded = (a.indeterminate_rows || []).concat(a.unknown_parameters || []);
      if (ungraded.length) {
        var names = [];
        ungraded.forEach(function (r) {
          if (names.indexOf(r.parameter) < 0) names.push(r.parameter);
        });
        return ['unmet', 'Not graded against any limit: ' + names.join(', ') + '.'];
      }
      if (!(a.evaluated_rows || []).length) {
        return ['unmet', 'No result in the sample could be graded.'];
      }
      return ['met', plural(a.evaluated_rows.length, 'determinand') +
        ' graded; verdict ' + a.verdict_state + '.'];
    }],
    design_derived: ['Borehole design', function (state) {
      var design = state.borehole_design;
      if (!design) return ['unmet', 'No borehole design has been derived.'];
      var errors = (design.flags || []).filter(function (f) { return f.level === 'error'; });
      if (errors.length) return ['unmet', errors[0].message];
      if (!(design.screens || []).length) return ['unmet', 'The design places no screen.'];
      return ['met', pyFixed(Number(design.total_screen_length_m), 1) +
        ' m of screen in ' + plural(design.screens.length, 'run') + '.'];
    }],
    cost_basis: ['Cost estimate', function (state) {
      var estimate = state.cost_estimate;
      if (!estimate) return ['unmet', 'No cost estimate has been computed.'];
      var depth = estimate.inputs ? estimate.inputs.total_depth_m : null;
      if (!depth) return ['unmet', 'The cost estimate has no total depth to price against.'];
      return ['met', 'Estimate priced for a ' + Math.round(depth) + ' m borehole.'];
    }],
    /* Every critical checklist item has an answer. Completeness, not
     * outcome: an answer of No is an answer, and the record states the
     * failure; an item left blank is a step the record cannot vouch for. The
     * gate used to look only at the photographs, so a record with three
     * photographed items answered and 35 critical ones blank was certified,
     * while its own summary said 35 critical items were still open. N/A is
     * an answer, and an answer that is none of the four is read as pending,
     * as evaluateChecklist reads it. */
    checklist_answered: ['Critical items answered', function (state) {
      var supervision = state.supervision || {};
      var items = supervision.items || loadChecklists();
      var responses = supervision.responses || {};
      var critical = items.filter(function (/** @type {Rec} */ item) { return item.critical; });
      if (!critical.length) return ['met', phrase('supervision.no_critical_items')];
      /** @type {Record<string, number>} */
      var openByStage = {};
      var titles = [];
      critical.forEach(function (/** @type {Rec} */ item) {
        var response = responses[item.item_id];
        var value = response && typeof response === 'object' ? response.status : response;
        var status = String(value || 'pending').trim().toLowerCase();
        if (RESPONSE_STATES.indexOf(status) < 0 || status === 'pending') {
          var title = stageTitle(item.checklist);
          if (!own(openByStage, title)) { openByStage[title] = 0; titles.push(title); }
          openByStage[title] += 1;
        }
      });
      if (titles.length) {
        var n = titles.reduce(function (sum, t) { return sum + openByStage[t]; }, 0);
        return ['unmet', phrase('supervision.critical_unanswered', { n: n,
          stages: andJoin(titles.map(function (t) {
            return phrase('supervision.open_in_stage', { n: openByStage[t], stage: t });
          })) })];
      }
      return ['met', phrase('supervision.critical_answered', { n: critical.length })];
    }],
    /* Every checklist item that needs a photograph has one. Which items do
     * is the checklist CSV's photo column, and one answered N/A needs none.
     * Presence is all this checks, and the detail says so whether or not it
     * is met, so a met requirement is never read as a verdict on the work. */
    photo_evidence: ['Photo evidence', function (state) {
      var supervision = state.supervision || {};
      var items = supervision.items || loadChecklists();
      var responses = supervision.responses || {};
      var evidence = supervision.evidence || {};
      /** @param {*} response */
      function status(response) {
        var value = response && typeof response === 'object' ? response.status : response;
        return String(value || 'pending').trim().toLowerCase();
      }
      /* the browser keeps {dataUrl}, the Streamlit app {b64} */
      /** @param {*} photo */
      function present(photo) {
        return !!(photo && typeof photo === 'object' &&
          (photo.dataUrl || photo.b64 || photo.bytes));
      }
      var wanted = items.filter(function (/** @type {Rec} */ item) {
        return item.photo_required && status(responses[item.item_id]) !== 'na';
      });
      var caveat = phrase('evidence.presence_only');
      if (!wanted.length) return ['met', phrase('evidence.none_required')];
      var missing = wanted.filter(function (/** @type {Rec} */ item) {
        return !present(evidence[item.item_id]);
      });
      if (missing.length) {
        return ['unmet', missing.map(function (/** @type {Rec} */ item) {
          return phrase('evidence.photo_missing',
            { stage: stageTitle(item.checklist), item: item.text });
        }).concat([caveat]).join(' ')];
      }
      return ['met', phrase('evidence.photos_present', { n: wanted.length }) + ' ' + caveat];
    }],
    /* Every decision number the report prints carries a band (PLAN.md step
     * 3.6), as every borehole carries a GPS fix: decision_numbers gives this
     * kind of report's numbers from the results the project holds. One with
     * nothing to work it out from is not counted; the requirements beside
     * this one say the test, the survey or the estimate is missing. */
    decision_bands: ['Decision bands', function (state, report) {
      var numbers = decisionNumbers(state, report);
      if (!numbers.length) return ['not_applicable', phrase('decision.gate_none')];
      var missing = numbers.filter(function (d) { return d.band === null; });
      if (missing.length) {
        return ['unmet', missing.map(function (d) {
          return phrase('decision.gate_missing', { name: d.name, reason: d.reason });
        }).join(' ')];
      }
      return ['met', phrase('decision.gate_met', {
        names: andJoin(numbers.map(function (d) { return d.name; })) })];
    }],
    no_errors: ['No fatal data problems', function (state) {
      var analysis = state.pump_analysis;
      var flags = readinessFlags([state.drilling_log, analysis, state.wq_assessment,
        state.borehole_design, state.cost_estimate,
        analysis ? analysis.test : null]);
      var errors = flags.filter(function (f) { return f && f.level === 'error'; });
      if (errors.length) {
        var seen = [];
        errors.forEach(function (f) {
          if (seen.indexOf(f.message) < 0) seen.push(f.message);
        });
        return ['unmet', seen.join('; ')];
      }
      return ['met', 'No module reported a fatal problem with the data.'];
    }],
  };

  /* What each report has to be able to stand behind. A pumping report makes
   * no claim about water quality; a handover report tells a village the
   * water is safe to drink, so it needs everything. */
  var READINESS_REPORTS = {
    /* The four reports that ask a decision on a number with a spread - how
     * deep to drill and how likely it is to work, what to pump and where to
     * set the pump, what to budget - need its band, as they need a position
     * (PLAN.md step 3.6). REPORT_DECISIONS says which numbers each prints. */
    completion: ['field_data', 'site_located', 'borehole_logged', 'readings_usable',
      'pumping_measured', 'yield_established', 'water_quality_panel',
      'water_quality_evaluable', 'design_derived', 'decision_bands', 'no_errors'],
    handover: ['field_data', 'site_located', 'borehole_logged', 'pumping_measured',
      'yield_established', 'water_quality_panel', 'water_quality_evaluable',
      'decision_bands', 'no_errors'],
    quality: ['field_data', 'site_located', 'water_quality_panel', 'water_quality_evaluable',
      'no_errors'],
    pumping: ['field_data', 'site_located', 'readings_usable', 'pumping_measured',
      'yield_established', 'decision_bands', 'no_errors'],
    geophysical: ['field_data', 'site_located', 'decision_bands'],
    /* an estimate is priced before anything is drilled, so it is judged on
     * its own inputs, not on a log and an as-built design it cannot have */
    costing: ['field_data', 'site_located', 'cost_basis', 'decision_bands', 'no_errors'],
    /* a supervision record vouches that the critical steps were done: each
     * needs an answer, and for the ones the checklist says need it, a
     * photograph is the evidence */
    supervision: ['field_data', 'site_located', 'checklist_answered', 'photo_evidence'],
    /* The asset documents and the payment certificate. Without an entry each
     * of these fell back to the completion set, so a plate for the headworks
     * was stamped PROVISIONAL for want of a water quality panel - which a
     * plate makes no claim about. What it does claim is that the identifier
     * on it leads back to this borehole, and that identifier is minted from
     * the position. */
    placard: ['field_data', 'site_located'],
    asset: ['field_data', 'site_located'],
    procurement: ['field_data', 'site_located', 'no_errors'],
  };

  /**
   * @param {Rec|null} state the project
   * @param {string} report the report the gate is for
   * @param {Record<string, *>|null} [overrides] keyed by requirement, a reason or {reason, by}
   */
  function assessReadiness(state, report, overrides) {
    var kind = READINESS_REPORTS[report] ? report : 'completion';
    var keys = READINESS_REPORTS[kind];
    var given = overrides || {};
    var requirements = keys.map(function (key) {
      var spec = READINESS_CHECKS[key];
      var found, detail;
      try {
        /* every check is given the report; only decision_bands reads it */
        var answer = spec[1](state || {}, kind);
        found = answer[0]; detail = answer[1];
      } catch (e) {
        /* a broken check is not a pass */
        found = 'unmet';
        detail = 'The ' + spec[0].toLowerCase() + ' check could not run: ' + e.message;
      }
      var override = own(given, key) ? given[key] : null;
      if (found === 'unmet' && override) {
        var reason = typeof override === 'string' ? override : (override.reason || '');
        var by = typeof override === 'string' ? '' : (override.by || '');
        return { key: key, title: spec[0], state: 'overridden', detail: detail,
          override_reason: reason, override_by: by };
      }
      return { key: key, title: spec[0], state: found, detail: detail,
        override_reason: '', override_by: '' };
    });

    var unmet = requirements.filter(function (r) { return r.state === 'unmet'; });
    var overridden = requirements.filter(function (r) { return r.state === 'overridden'; });
    var overall = unmet.length ? 'not_ready'
      : (overridden.length ? 'ready_with_overrides' : 'ready');
    var assumptions = [];
    try {
      var analysis = (state || {}).pump_analysis;
      flagsWithCode(readinessFlags([(state || {}).drilling_log, analysis,
        (state || {}).wq_assessment, (state || {}).borehole_design,
        analysis ? analysis.test : null]), UNIT_ASSUMPTIONS)
        .forEach(function (f) {
          if (assumptions.indexOf(f.message) < 0) assumptions.push(f.message);
        });
    } catch (e) { /* a malformed object costs the list, not the gate */ }

    /* A bundled file whose measurements are real but whose blank columns were
     * filled in illustratively. Not blocking - the readings are somebody's
     * real readings - but the reader should know which column is which. The
     * Python engine states this, so the browser has to state it in the same
     * words or the same project yields two different documents. */
    try {
      var known = loadSampleProvenance();
      var sources = (state || {}).sources || {};
      Object.keys(sources).forEach(function (role) {
        var record = sourceProvenance(sources[role], known);
        if (!record || record.kind !== 'reconstructed') return;
        var line = record.file.split('/').pop() + ': ' + record.note;
        if (assumptions.indexOf(line) < 0) assumptions.push(line);
      });
    } catch (e) { /* as above */ }

    var summary;
    if (overall === 'ready') {
      summary = 'All certification requirements are met.';
    } else if (overall === 'ready_with_overrides') {
      summary = 'Issued on override: ' +
        overridden.map(function (r) { return r.title; }).join(', ') + '.';
    } else {
      summary = 'Not ready to certify - outstanding: ' +
        unmet.map(function (r) { return r.title; }).join(', ') + '.';
    }
    return {
      report: kind, requirements: requirements, assumptions: assumptions,
      unmet: unmet, overridden: overridden, state: overall,
      /* an override makes the document issuable, never certifiable */
      is_certifiable: overall === 'ready',
      summary: summary,
    };
  }

  Object.assign(C, {
    assessReadiness: assessReadiness,
    loadSampleProvenance: loadSampleProvenance,
    sourceProvenance: sourceProvenance,
    READINESS_REPORTS: READINESS_REPORTS,
    READINESS_CHECKS: READINESS_CHECKS,
  });


  PAGES.portfolio = function () {
    var summaries = derived.portfolio || [];
    var chosenIndex = Math.min(store.get('portfolio.site', 0), Math.max(summaries.length - 1, 0));

    var nodes = [
      pageHead('Portfolio', 'Many boreholes side by side. Save a project from ' +
        'any page — each file carries a short summary — then drop several of ' +
        'them here for a status map, a comparison table and the headline ' +
        'figures a water manager needs.'),
      card('Saved projects', [
        el('p.muted', 'Project files from this app (.gwt.json) and from the ' +
          'Streamlit app (.yaml) both work, so a programme run across the two ' +
          'still pools into one view.'),
        el('div.btn-row', [
          button('Add project files', async function () {
            var list = await S.pickFile('.json,.gwt,.yaml,.yml', true);
            if (!list || !list.length) return;
            var loaded = derived.portfolio ? derived.portfolio.slice() : [];
            var ledgers = portfolioLedgers().slice();
            var works = portfolioWorks().slice();
            /* the files, by their hashes, which a calibration report over the
             * pooled ledgers is issued from (PLAN.md step 8.1) */
            var files = (derived.portfolioFiles || []).slice();
            var skipped = 0;
            for (var i = 0; i < list.length; i++) {
              try {
                var text = await S.readFile(list[i], 'text');
                var entry = projectFileEntry(list[i].name, text);
                loaded.push(entry.summary);
                ledgers.push(entry.ledger);
                works.push(entry.works);
                files.push(projectFileEvidence(list[i].name, text));
              } catch (e) { skipped += 1; }
            }
            derived.portfolio = loaded;
            derived.portfolioLedgers = ledgers;
            derived.portfolioWorks = works;
            derived.portfolioFiles = files;
            S.toast(loaded.length + ' ' + S.plural(loaded.length, 'project') +
              ' loaded' + (skipped ? ', ' + skipped + ' skipped' : '') + '.',
            skipped ? 'warn' : 'ok');
            render();
          }),
          summaries.length ? button('Add this project', function () {
            derived.portfolioLedgers = portfolioLedgers().concat([currentLedger()]);
            derived.portfolioWorks = portfolioWorks().concat([currentWorks()]);
            derived.portfolio = (derived.portfolio || []).concat([projectSummary()]);
            render();
          }, { variant: 'ghost' }) : null,
          summaries.length ? button('Clear', function () {
            derived.portfolio = null; derived.portfolioLedgers = null; derived.portfolioWorks = null;
            derived.portfolioFiles = null;
            render();
          }, { variant: 'ghost' }) : null,
        ]),
        !summaries.length ? el('p.muted', 'Nothing loaded yet. You can also ' +
          'start with the project open in this window:') : null,
        !summaries.length ? button('Start from the open project', function () {
          derived.portfolio = [projectSummary()];
          derived.portfolioLedgers = [currentLedger()];
          derived.portfolioWorks = [currentWorks()];
          render();
        }, { variant: 'ghost' }) : null,
      ]),
    ];

    if (!summaries.length) {
      nodes.push(S.empty('Load two or more saved project files to build the ' +
        'portfolio: a status map, a comparison table and the programme figures.'));
      nodes.push(calibrationSetsCard([]));
      return nodes;
    }

    var stats = C.portfolioStats(summaries);
    nodes.push(card('Programme', [
      S.statRow([
        S.stat('Projects', String(stats.n_projects)),
        S.stat('Successful', String(stats.n_successful),
          'of ' + stats.n_drilled + ' drilled'),
        S.stat('Success rate', stats.success_rate !== null
          ? stats.success_rate.toFixed(0) + '%' : '—', 'over drilled holes'),
        S.stat('Mean safe yield', stats.mean_safe_yield_m3_per_h !== null
          ? stats.mean_safe_yield_m3_per_h.toFixed(2) + ' m³/h' : '—'),
        S.stat('Mean cost/m', stats.mean_cost_per_meter_usd !== null
          ? S.money(stats.mean_cost_per_meter_usd, 0) : '—'),
      ]),
      /* Three rates, not one. A single "safe to drink" tile counted an
       * aesthetic exceedance as safe and hid national-standard failures
       * inside it, so a breached programme showed 100%. */
      S.statRow([
        S.stat('Water compliant', stats.wq_compliant_rate !== null
          ? stats.wq_compliant_rate.toFixed(0) + '%' : '—',
          'of ' + stats.n_wq_assessed + ' sampled: meets every health and ' +
          'national limit'),
        S.stat('Water failing', stats.wq_fail_rate !== null
          ? stats.wq_fail_rate.toFixed(0) + '%' : '—',
          'exceeds a health guideline or a national limit'),
        S.stat('Water unproven', stats.wq_unproven_rate !== null
          ? stats.wq_unproven_rate.toFixed(0) + '%' : '—',
          'results incomplete or not evaluable'),
      ]),
      stats.n_status_unrecognised
        ? el('div.callout.callout-warn', el('p', stats.n_status_unrecognised +
          ' ' + S.plural(stats.n_status_unrecognised, 'project') +
          (stats.n_status_unrecognised === 1 ? ' carries' : ' carry') +
          ' a status this toolkit does not recognise; ' +
          (stats.n_status_unrecognised === 1 ? 'it is' : 'they are') +
          ' counted as neither successful nor dry. Correct the status on ' +
          'the drilling log.'))
        : null,
    ].filter(Boolean)));

    var points = C.portfolioPoints(summaries);
    nodes.push(card('Where they are', [
      points.length ? charts.figure(charts.siteMap({
        context: (mapLayers().adminBoundaries || {}).features || [],
        points: points.map(function (p) {
          return {
            lon: p.lon, lat: p.lat, label: p.label, size: 5.5,
            colour: C.STATUS_COLORS[p.status],
          };
        }),
        title: 'Borehole portfolio',
        legendItems: Object.keys(C.STATUS_LABELS).map(function (key) {
          return { label: C.STATUS_LABELS[key], colour: C.STATUS_COLORS[key] };
        }),
        width: 640, height: 560,
      }), 'Project status by location', { filename: 'portfolio_map' })
        : S.empty('Add GPS coordinates to the projects to place them on the map.'),
    ]));

    nodes.push(card('Comparison', [
      S.table([
        { key: 'Community', label: 'Community' },
        { key: 'District', label: 'District' },
        { key: 'Status', label: 'Status' },
        { key: 'Depth (m)', label: 'Depth (m)', align: 'right' },
        { key: 'Safe yield (m3/h)', label: 'Safe yield (m³/h)', align: 'right' },
        { key: 'Water', label: 'Water' },
        { key: 'Cost/m (USD)', label: 'Cost/m (USD)', align: 'right' },
      ], C.portfolioRows(summaries), {
        rowClass: function (row, i) {
          return C.classifyStatus(summaries[i]) === 'dry' ? 'row-bad' : '';
        },
      }),
    ]));

    var chosen = summaries[chosenIndex];
    nodes.push(card('Site detail', [
      el('p.muted', 'Drill into one site for its full record and a one-page brief.'),
      field('Site', S.selectInput(String(chosenIndex),
        summaries.map(function (s, i) {
          return { value: String(i), label: C.portfolioSiteLabel(s, i) };
        }), function (value) {
          store.set('portfolio.site', Number(value)); render();
        })),
      S.table([
        { key: '0', label: 'Field' },
        { key: '1', label: 'Value' },
      ], C.portfolioSiteDetail(chosen)),
      el('div.btn-row', [
        button('Download site brief (.txt)', function () {
          var name = String(chosen.community || 'site').trim().replace(/\s+/g, '_');
          S.download(name + '_brief.txt', C.portfolioOnePager(chosen), 'text/plain');
        }),
      ]),
    ]));

    nodes.push(scorecardsCard(summaries));

    /* the files' ledgers of predictions and outcomes, pooled (PLAN.md step
     * 5.1): each point once, the drilled ones beside what was found */
    var ledgers = portfolioLedgers();
    var pooled = C.poolLedgers(summaries.map(function (s, i) {
      return [C.portfolioSiteLabel(s), ledgers[i] || null];
    }));
    var table = C.ledgerRows(pooled);
    nodes.push(card('Predictions and outcomes', [
      el('p.muted', C.ledgerSummary(pooled)),
      table.rows.length ? S.table(table.header, table.rows) : null,
      pooled.length ? el('div.btn-row', [
        /* every entry with its numbers, for the calibration that learns
         * from them (PLAN.md step 5.2); the Python app writes the same file */
        button('Download the pooled ledger (.json)', function () {
          S.download('pooled_ledger.json', JSON.stringify(pooled, null, 1), 'application/json');
        }),
      ]) : null,
    ].filter(Boolean)));
    if (pooled.length) nodes.push(calibrationCard(pooled));
    nodes.push(calibrationSetsCard(pooled));
    return nodes;
  };

  /* The calibration set in force in this browser (PLAN.md step 5.3): its
   * name and what it changes, to download, to replace with a file or to
   * return to the provisional default; with pooled ledgers, a set fitted to
   * them and reviewed beside it; and sets other organisations adopted,
   * pooled into one and reviewed the same way (PLAN.md step 5.5). Either is
   * for a named person to adopt and put in force. Nothing changes until
   * someone does. */
  function calibrationSetsCard(pooled) {
    var cfg = config();
    var held = C.inForce(cfg);
    var changes = C.setChanges(held);
    /** @type {Array<Node|null>} */
    var body = [
      el('p.muted', C.phrase('calibration_sets.page_lead')),
      el('p', C.phrase('calibration_sets.page_in_force', { name: C.setName(held) })),
      changes.length ? el('ul', changes.map(function (line) { return el('li', line); })) : null,
      el('div.btn-row', [
        button(C.phrase('calibration_sets.page_download'), function () {
          S.download('calibration.yaml', C.setYaml(held), 'application/x-yaml');
        }),
        held.version !== 0 ? button(C.phrase('calibration_sets.page_default'), function () {
          putSetInForce(C.defaultSet());
        }, { variant: 'ghost' }) : null,
      ]),
      el('p.muted', C.phrase('calibration_sets.page_share')),
      field(C.phrase('calibration_sets.page_load'), button(C.phrase('calibration_sets.page_load_button'),
        loadSetFile, { variant: 'ghost' })),
    ];
    if (!pooled.length) {
      body.push(el('p.muted', C.phrase('calibration_sets.page_fit_none')));
    } else {
      /* a fit is reviewed while the files it was fitted to and the set it
       * was fitted under are the ones on the page */
      var basis = JSON.stringify([pooled, held]);
      body.push(el('div.btn-row', [
        button(C.phrase('calibration_sets.page_fit'), function () {
          derived.calibrationCandidate = { set: C.fitSet(pooled, localDate(), cfg), basis: basis };
          render();
        }, { title: C.phrase('calibration_sets.page_fit_help') }),
      ]));
      var fitted = derived.calibrationCandidate;
      if (fitted && fitted.basis === basis) {
        body.push(setReviewNode(fitted.set, held, cfg, function () { derived.calibrationCandidate = null; }));
      }
    }
    /* sets from other organisations, pooled, reviewed while the set in
     * force they were pooled beside is the one in force */
    body.push(el('h3', C.phrase('calibration_sets.page_pool')));
    body.push(el('p.muted', C.phrase('calibration_sets.page_pool_help')));
    body.push(field(C.phrase('calibration_sets.page_pool_load'),
      button(C.phrase('calibration_sets.page_pool_button'), function () { poolSetFiles(cfg); },
        { variant: 'ghost' })));
    var pooledSet = derived.calibrationPooled;
    if (pooledSet && pooledSet.basis === JSON.stringify(held)) {
      body.push(setReviewNode(pooledSet.set, held, cfg, function () { derived.calibrationPooled = null; }));
    }
    return card(C.phrase('calibration_sets.page_heading'), body.filter(Boolean));
  }

  /* calibration.yaml files other organisations adopted, pooled into one set
   * for review (PLAN.md step 5.5); a file that is not a set, or a set that
   * cannot be pooled, is refused in a sentence naming its file. */
  async function poolSetFiles(cfg) {
    var list = await S.pickFile('.yaml,.yml', true);
    if (!list || !list.length) return;
    var raws = [], labels = [];
    for (var i = 0; i < list.length; i++) {
      labels.push(list[i].name);
      try {
        raws.push(S.parseYaml(await S.readFile(list[i], 'text')));
      } catch (e) {
        raws.push(null);
      }
    }
    derived.calibrationPooled = null;
    try {
      derived.calibrationPooled = { set: C.poolSets(raws, localDate(), cfg, labels),
        basis: JSON.stringify(C.inForce(cfg)) };
    } catch (e) {
      S.toast(/** @type {Error} */ (e).message, 'error');
    }
    render();
  }

  /* A fitted or pooled set's review beside the set in force, and where it
   * fits anything, the name of whoever adopts it, their organisation (the
   * one the reports are branded with, to start) and a contact, and the
   * button that adopts it; done() drops the review once it is adopted. */
  function setReviewNode(candidate, held, cfg, done) {
    var review = C.setReview(candidate, cfg);
    var adopter = S.textInput('', function () {},
      { 'aria-label': C.phrase('calibration_sets.page_adopter') });
    var organisation = S.textInput(cfg.style.organisation || '', function () {},
      { 'aria-label': C.phrase('calibration_sets.page_organisation') });
    var contact = S.textInput('', function () {},
      { 'aria-label': C.phrase('calibration_sets.page_contact') });
    return el('div.calibration-review', [
      el('h3', review.title),
      review.summary.map(function (text) { return el('p', text); }),
      review.tables.map(function (table) {
        return [el('p.muted', table.caption), S.table(table.header, table.rows)];
      }).flat(),
      review.adoptable ? field(C.phrase('calibration_sets.page_adopter'), adopter,
        C.phrase('calibration_sets.page_adopter_help')) : null,
      review.adoptable ? field(C.phrase('calibration_sets.page_organisation'), organisation,
        C.phrase('calibration_sets.page_organisation_help')) : null,
      review.adoptable ? field(C.phrase('calibration_sets.page_contact'), contact,
        C.phrase('calibration_sets.page_contact_help')) : null,
      review.adoptable ? el('div.btn-row', [
        button(C.phrase('calibration_sets.page_adopt'), function () {
          var adopted;
          try {
            adopted = C.adoptSet(candidate, /** @type {HTMLInputElement} */ (adopter).value,
              localDate(), held, /** @type {HTMLInputElement} */ (organisation).value,
              /** @type {HTMLInputElement} */ (contact).value);
          } catch (e) {
            S.toast(e.message, 'error');
            return;
          }
          if (putSetInForce(adopted)) done();
        }),
      ]) : null,
    ].flat().filter(Boolean));
  }

  /* Put the set s in force in this browser, or say why not; true where it
   * is. Every page reads by it from here, and the survey already inverted is
   * read by it again. */
  function putSetInForce(s) {
    var checked;
    try {
      checked = C.checkInForce(s);
    } catch (e) {
      S.toast(e.message, 'error');
      return false;
    }
    store.set('calibration', checked.version === 0 ? null : checked);
    S.toast(C.phrase('calibration_sets.page_put_in_force', { name: C.setName(checked) }), 'ok');
    recompute().then(render);
    render();
    return true;
  }

  /* A calibration.yaml, read whole or refused, put in force. */
  async function loadSetFile() {
    var file = await S.pickFile('.yaml,.yml');
    if (!file) return;
    var raw;
    try {
      raw = S.parseYaml(await S.readFile(file, 'text'));
    } catch (e) {
      S.toast(C.phrase('calibration_sets.unreadable',
        { why: C.phrase('calibration_sets.why_not_mapping') }), 'error');
      return;
    }
    putSetInForce(raw);
  }

  /* The calibration report over the pooled ledgers (PLAN.md step 5.2): its
   * summary and two figures on the page, and the whole report, with the
   * band, the odds and the hit rates, as a Word document. */
  function calibrationCard(pooled) {
    var cfg = config();
    var content = C.calibrationContent(pooled, localDate(), cfg);
    var figures = calibrationFigureList(pooled, content, cfg);
    return card('Calibration', [
      content.summary.slice(1).map(function (text) { return el('p', text); }),
      figures.map(function (fig) {
        return charts.figure(fig.draw(), fig.caption, { filename: 'calibration_' + fig.key });
      }),
      el('div.btn-row', [
        button('Build the calibration report (.docx)', function (event) {
          buildCalibration(pooled, event.target);
        }),
      ]),
    ].flat());
  }

  /* the figures the report's content names, each with what draws it */
  function calibrationFigureList(pooled, content, cfg) {
    var draws = {
      depth: function () { return charts.depthCalibration(C.depthScores(pooled, cfg)); },
      reliability: function () { return charts.reliabilityDiagram(C.oddsScores(pooled, cfg)); },
    };
    var out = [];
    content.sections.forEach(function (section) {
      section.figures.forEach(function (fig) {
        out.push({ key: fig.key, caption: fig.caption, draw: draws[fig.key] });
      });
    });
    return out;
  }

  async function buildCalibration(pooled, node) {
    var host = node ? node.closest('.card') : $('#page-host');
    try {
      await need(REPORT_BUNDLES);
    } catch (e) {
      S.toast('Could not build the calibration report: ' + e.message, 'error');
      return;
    }
    charts.usePrintPalette(true);
    try {
      await S.withBusy(host, 'Building the calibration report…', async function () {
        var cfg = config();
        var issue = issueFor('calibration', { files: derived.portfolioFiles || [] });
        var content = C.calibrationContent(pooled, issue.issued_on, cfg);
        var figures = {};
        var list = calibrationFigureList(pooled, content, cfg);
        /* one at a time, so that no more than one figure's canvas is held */
        for (var i = 0; i < list.length; i++) figures[list[i].key] = await charts.toPng(list[i].draw());
        var builder = GWT.docx.calibrationReport({ style: cfg.style, content: content, figures: figures,
          issue: issue });
        /* saved first: the builder has no record until it has built the document */
        var calibrationBytes = await builder.save('Calibration_Report.docx');
        recordIssue(builder.record, 'Calibration_Report.docx', calibrationBytes);
        S.toast(savedWords('Calibration_Report.docx', builder.record), 'ok');
      });
    } catch (e) {
      S.toast('Could not build the calibration report: ' + e.message, 'error');
      console.error(e);
    } finally {
      charts.usePrintPalette(false);
    }
  }

  /* The ledgers of the project files on the Portfolio page, by the index of
   * their summaries; a summary added before ledgers were kept has none. */
  function portfolioLedgers() {
    var summaries = derived.portfolio || [];
    var ledgers = derived.portfolioLedgers || [];
    return summaries.map(function (_, i) { return ledgers[i] || null; });
  }

  /* likewise their works records (PLAN.md step 6.3), null for a file with none */
  function portfolioWorks() {
    var summaries = derived.portfolio || [];
    var works = derived.portfolioWorks || [];
    return summaries.map(function (_, i) { return works[i] || null; });
  }

  /* each project file on the Portfolio page as the contractor scorecards
   * read it: [label, works record, ledger] */
  function scorecardFiles(summaries) {
    var ledgers = portfolioLedgers(), works = portfolioWorks();
    return summaries.map(function (s, i) { return [C.portfolioSiteLabel(s), works[i], ledgers[i]]; });
  }

  /* The contractor scorecards over the files (PLAN.md step 6.3): the
   * summary, the scorecards and the checks that failed on the page, and the
   * whole report as a Word document. The Streamlit app shows the same. */
  function scorecardsCard(summaries) {
    var cfg = config();
    var files = scorecardFiles(summaries);
    var content = C.scorecardContent(files, localDate(), cfg);
    /** @type {Array<Node|null>} */
    var body = [el('p.muted', C.phrase('scorecards.page_lead'))];
    content.summary.forEach(function (text) { body.push(el('p', text)); });
    content.sections.forEach(function (section) {
      if (section.key !== 'cards' && section.key !== 'checks') return;
      section.tables.forEach(function (table) {
        body.push(el('p.muted', table.caption));
        body.push(S.table(table.header, table.rows));
      });
    });
    body.push(el('div.btn-row', [
      button(C.phrase('scorecards.page_build'), function (event) {
        buildScorecards(files, event.target);
      }, { title: C.phrase('scorecards.page_build_help') }),
    ]));
    return card(C.phrase('scorecards.page_heading'), body.filter(Boolean));
  }

  async function buildScorecards(files, node) {
    var host = node ? node.closest('.card') : $('#page-host');
    try {
      await need(REPORT_BUNDLES);
    } catch (e) {
      S.toast('Could not build the contractor scorecards: ' + e.message, 'error');
      return;
    }
    try {
      await S.withBusy(host, 'Building the contractor scorecards…', async function () {
        var cfg = config();
        /* issued from the project files on the page (PLAN.md step 8.1) */
        var issue = issueFor('scorecards', { files: derived.portfolioFiles || [] });
        var builder = GWT.docx.scorecardReport({ style: cfg.style,
          content: C.scorecardContent(files, issue.issued_on, cfg), issue: issue });
        /* saved first: the builder has no record until it has built the document */
        var scorecardBytes = await builder.save('Contractor_Scorecards.docx');
        recordIssue(builder.record, 'Contractor_Scorecards.docx', scorecardBytes);
        S.toast(savedWords('Contractor_Scorecards.docx', builder.record), 'ok');
      });
    } catch (e) {
      S.toast('Could not build the contractor scorecards: ' + e.message, 'error');
      console.error(e);
    }
  }

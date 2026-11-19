
  /* --- depth spine ---------------------------------------------------------- */

  /* The sign-off layer, as a layer rather than a second application.
   *
   * Every stage produces one professional opinion. The toolkit recommends it,
   * a named person accepts or overrides it, and an override carries a reason
   * that travels into the report. The ledger lives in the project state, so it
   * is saved with the project and survives a refresh - a signature that
   * evaporated on reload would be worth nothing. */
  var SPINE_STAGES = [
    ['design', 'Design'], ['quality', 'Water quality'], ['costing', 'Costing & BoQ'],
  ];

  function spineLedger() { return store.get('spine.ledger') || {}; }

  function spineSignatory() {
    return store.get('spine.signatory') ||
      store.get('site.supervisor') || 'unsigned';
  }

  function spineDecide(stage, record) {
    var ledger = Object.assign({}, spineLedger());
    if (record) ledger[stage] = record; else delete ledger[stage];
    store.set('spine.ledger', ledger);
    render();
  }

  function spineStamp() {
    return new Date().toISOString().slice(0, 16).replace('T', ' ');
  }

  /* Accepting is one press. Overriding costs a value and a reason, because the
   * override is the thing that ends up in front of the client with a name on
   * it. */
  function signOffCard(spec) {
    var record = spineLedger()[spec.stage] || null;
    if (record) {
      return card('Signed off', [
        el('div.callout' + (record.status === 'accepted' ? '.callout-ok' : '.callout-warn'), [
          el('p', el('strong',
            (record.status === 'accepted' ? 'Accepted' : 'Overridden') +
            ' — ' + record.value)),
          el('p.muted', record.signatory + ' · ' + record.at +
            (record.clean ? '' : ' · signed over an open flag')),
          record.status === 'overridden' ? el('p', [
            el('span.muted', 'The toolkit recommended ' + record.recommended + '. '),
            record.reason,
          ]) : null,
        ]),
        button('Reopen decision', function () { spineDecide(spec.stage, null); },
          { variant: 'ghost' }),
      ]);
    }
    var overrideValue = { value: spec.overrideStart, reason: '' };
    var open = store.get('spine.overriding') === spec.stage;
    return card('Sign off', [
      el('p.muted', spec.writesTo +
        (spec.clean ? '.' : ' · one check is still flagged.')),
      field('Signatory', S.textInput(spineSignatory(), function (value) {
        store.set('spine.signatory', value);
      }), 'Named on the decision, and in the report.'),
      open ? el('div.section', [
        spec.overrideChoices
          ? field(spec.overrideLabel, S.selectInput(spec.overrideStart,
            spec.overrideChoices, function (value) { overrideValue.value = value; }))
          : field(spec.overrideLabel + ' (' + spec.overrideUnit + ')',
            S.numberInput(spec.overrideStart, function (value) {
              overrideValue.value = value;
            }, { step: spec.overrideStep || 0.01 })),
        field('Reason — required, and it goes in the report',
          S.textInput('', function (value) { overrideValue.reason = value; })),
        el('div.btn-row', [
          button('Record override', function () {
            if (!String(overrideValue.reason).trim()) {
              S.toast('An override needs a reason.', 'warn');
              return;
            }
            store.set('spine.overriding', null);
            spineDecide(spec.stage, {
              stage: spec.stage, status: 'overridden',
              value: spec.formatOverride
                ? spec.formatOverride(overrideValue.value) : String(overrideValue.value),
              recommended: spec.recommended,
              reason: String(overrideValue.reason).trim(),
              signatory: spineSignatory(), at: spineStamp(), clean: spec.clean,
            });
          }),
          button('Cancel', function () {
            store.set('spine.overriding', null); render();
          }, { variant: 'ghost' }),
        ]),
      ]) : null,
      el('div.btn-row', [
        button('Accept ' + (spec.acceptLabel || spec.recommended), function () {
          spineDecide(spec.stage, {
            stage: spec.stage, status: 'accepted', value: spec.recommended,
            recommended: spec.recommended, signatory: spineSignatory(),
            at: spineStamp(), clean: spec.clean,
          });
        }),
        open ? null : button('Override…', function () {
          store.set('spine.overriding', spec.stage); render();
        }, { variant: 'ghost' }),
      ]),
    ]);
  }

  /* Where a page prints the yield recommendation's pump intake and the
   * borehole design has moved that depth out of a screen into plain casing,
   * say so in the design's words: the design page, the drawing and the
   * completion and handover reports all print design.pump_intake_m. */
  function pumpIntakeMovedNote() {
    var design = derived.design;
    if (!design || !design.flags) return null;
    var moved = design.flags.filter(function (f) { return f.code === 'pump_intake_moved'; });
    if (!moved.length) return null;
    return el('div.callout', [
      el('p', moved[0].message),
      el('p.muted', 'The borehole design and the completion and handover reports ' +
        'print the intake at ' + C.formatG(design.pump_intake_m) + ' m.'),
    ]);
  }

  function flagList(flags, empty) {
    if (!flags || !flags.length) {
      return el('div.callout.callout-ok', el('p', empty));
    }
    return S.checkList(flags.map(function (f) {
      return {
        level: f.level, message: f.message,
        detail: f.code + (f.context ? ' · ' + f.context : ''),
      };
    }));
  }

  /* Moving a screen re-runs the design and everything downstream of it, and
   * invalidates the design and costing signatures: a signature has to belong
   * to the numbers that were in front of the person at the time. */
  function commitSpineScreens(screens) {
    store.set('design.screens', screens && screens.length
      ? screens.map(function (s) { return [s.top, s.base]; }) : null);
    var ledger = Object.assign({}, spineLedger());
    delete ledger.design; delete ledger.costing;
    store.set('spine.ledger', ledger);
    rebuildDesign(); rebuildCosting();
    render();
  }

  /* Direct manipulation of the screened intervals. Dragging moves the drawing
   * locally, because a pointer has to feel attached to what it is dragging;
   * releasing hands the intervals back to the engine, which re-runs
   * designBorehole and everything downstream. No hydrogeological rule is
   * applied here - the clamping is only enough to keep the drawing sane while
   * the pointer is down; the real validation is the designer's. */
  function attachScreenDrag(svg, view, redraw) {
    var limits = view.section.screenLimits;
    var base = (view.design.screens || []).map(function (s) {
      return { top: s.top, base: s.base };
    });

    function round(n) { return Math.round(n * 10) / 10; }
    function clamp(list) {
      return list.map(function (s) {
        var top = Math.max(limits.top, Math.min(s.top, limits.base - limits.minLength));
        var bottom = Math.max(top + limits.minLength, Math.min(s.base, limits.base));
        return { top: round(top), base: round(bottom) };
      });
    }
    function moved(origin, index, edge, dm) {
      return clamp(origin.map(function (s, i) {
        if (i !== index) return { top: s.top, base: s.base };
        if (edge === 'top') return { top: round(s.top + dm), base: s.base };
        if (edge === 'base') return { top: s.top, base: round(s.base + dm) };
        return { top: round(s.top + dm), base: round(s.base + dm) };
      }));
    }

    svg.addEventListener('pointerdown', function (event) {
      var target = event.target;
      var index = target.getAttribute && target.getAttribute('data-screen');
      if (index === null || index === undefined) return;
      event.preventDefault();
      var edge = target.getAttribute('data-edge');
      var startY = event.clientY;
      var origin = base.map(function (s) { return { top: s.top, base: s.base }; });
      var latest = origin;
      var scale = svg.spineScale;
      /* the SVG is scaled to its box, so client pixels become user units
       * through the rendered height before they become metres. A zero-height
       * box (hidden tab, mid-layout) would make that ratio infinite and send
       * the screen to the bottom of the hole on the first move. */
      var rendered = svg.getBoundingClientRect().height;
      if (!(rendered > 0)) return;
      var factor = svg.viewBox.baseVal.height / rendered;

      function move(e) {
        var dm = round(scale.depthAt((e.clientY - startY) * factor));
        latest = moved(origin, Number(index), edge, dm);
        redraw(latest);
      }
      function end() {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', end);
        window.removeEventListener('pointercancel', end);
        commitSpineScreens(latest);
      }
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', end);
      window.addEventListener('pointercancel', end);
    });

    svg.addEventListener('keydown', function (event) {
      var target = event.target;
      var index = target.getAttribute && target.getAttribute('data-screen');
      if (index === null || index === undefined) return;
      var edge = target.getAttribute('data-edge');
      if (edge === 'body') return;
      var step = event.shiftKey ? 1 : 0.1;
      var dm = event.key === 'ArrowUp' ? -step : (event.key === 'ArrowDown' ? step : 0);
      if (!dm) return;
      event.preventDefault();
      commitSpineScreens(moved(base, Number(index), edge, dm));
    });
  }

  PAGES.spine = function () {
    var head = pageHead('Depth Spine', 'The whole borehole on one depth axis: ' +
      'the cuttings log, the casing string and the water levels registered ' +
      'against the same ruler, with the screened intervals editable. ' +
      'Everything shown is computed here, by the same functions that write ' +
      'the reports.');

    if (!derived.log) {
      return [head, S.empty('Load a drilling log first — the spine is drawn ' +
        'from the logged hole.',
      el('div.btn-row', [
        button('Borehole design', function () { goto('design'); }),
        button('Overview', function () { goto('overview'); }, { variant: 'ghost' }),
      ]))];
    }

    var view;
    try {
      view = C.buildSpineView({
        name: store.get('site.community') || 'Borehole',
        log: derived.log, analysis: derived.analysis,
        assessment: derived.assessment, config: config(),
        mobilisationDistanceKm: store.get('costing.mobilisation_km') || 0,
        /* the same rates and percentages the Costing page uses: the spine's
         * price is the one a named person signs */
        costing: Object.assign({
          rates: costingRates(),
          wqSamples: store.get('costing.wq_samples'),
          handpumps: store.get('costing.handpumps'),
          overburdenM: overburdenFromData(),
        }, costingOptions()),
      }, store.get('design.screens'));
    } catch (e) {
      return [head, el('div.callout.callout-bad', [
        el('p', el('strong', 'The spine could not be built.')),
        el('p', e.message),
      ])];
    }

    var stage = store.get('spine.stage', 'design');
    var stages = SPINE_STAGES.filter(function (s) {
      return s[0] !== 'quality' || view.quality;
    });
    if (!stages.some(function (s) { return s[0] === stage; })) stage = 'design';
    var ledger = spineLedger();
    var signed = stages.filter(function (s) { return ledger[s[0]]; }).length;

    var nodes = [head, card('Stage', [
      el('div.chips', stages.map(function (s) {
        var record = ledger[s[0]];
        return el('button.chip' + (stage === s[0] ? '.active' : ''), {
          type: 'button',
          onclick: function () { store.set('spine.stage', s[0]); render(); },
        }, [s[1], record ? ' ' : null,
          record ? S.badge(record.status === 'accepted' ? '✓' : '↺',
            record.status === 'accepted' ? 'ok' : 'warn') : null]);
      })),
      el('p.muted', signed + ' of ' + stages.length + ' stages signed. ' +
        (view.edited ? 'The design on this section is the analyst\'s, not the ' +
          'automatic placement.' : 'Screens are the automatic placement.')),
    ])];

    if (stage === 'design') nodes = nodes.concat(spineDesignStage(view));
    else if (stage === 'quality') nodes = nodes.concat(spineQualityStage(view));
    else nodes = nodes.concat(spineCostingStage(view));

    nodes.push(nextStep('Price the design on the section.', 'Costing & BoQ', 'costing'));
    return nodes;
  };

  function spineDesignStage(view) {
    var section = view.section, design = view.design, y = design.yield;
    var errors = design.flags.filter(function (f) { return f.level === 'error'; });
    /* the intake beside a design is the design's (section.levels.pumpIntake
     * is design.pump_intake_m): it may have moved the yield recommendation's
     * depth out of a screen into plain casing */
    var levels = section.levels || {};
    var intakeM = levels.pumpIntake !== null && levels.pumpIntake !== undefined
      ? levels.pumpIntake : y.pumpDepthM;
    var intakeMoved = intakeM !== y.pumpDepthM && y.pumpDepthM !== null &&
      y.pumpDepthM !== undefined;
    var clean = !errors.length &&
      design.flags.every(function (f) { return f.level === 'info'; });

    /* one holder redrawn in place, so a drag does not re-render the page */
    var holder = el('div');
    function draw(screens) {
      S.clear(holder);
      var svg = charts.depthSpine(view, { screens: screens, width: 720, height: 640 });
      attachScreenDrag(svg, view, draw);
      holder.appendChild(svg);
    }
    draw(null);

    return [
      card('The hole', [
        S.statRow([
          S.stat('Drilled', section.totalDepth.toFixed(1) + ' m'),
          S.stat('Water strikes', section.waterStrikes.length
            ? section.waterStrikes.map(function (s) { return s.toFixed(0); }).join(', ') + ' m'
            : 'none'),
          S.stat('Screened', design.totalScreenM + ' m',
            design.screenShare + '% of the hole'),
          S.stat('Casing', section.casingDiameterIn + '″ ' + section.casingMaterial,
            'slot ' + section.slotMm + ' mm'),
        ]),
        holder,
        el('p.muted', 'Drag a screen or one of its handles, or focus a handle ' +
          'and use the arrow keys — 0.1 m a press, 1 m with Shift. On release ' +
          'the toolkit re-runs the design: the casing string, the annulus, the ' +
          'checks and the bill of quantities all come back from the engine, so ' +
          'nothing here is a second opinion. The Borehole design page and the ' +
          'completion report follow the same screens.'),
        view.edited ? button('Back to the generated design', function () {
          commitSpineScreens(null);
        }, { variant: 'ghost' }) : null,
      ]),

      card('Recommended safe yield', y.pending ? [
        el('div.callout.callout-warn', [
          el('p', el('strong', 'Pending')),
          el('p', y.pending),
        ]),
      ] : [
        S.statRow([
          S.stat('Safe yield', y.rangeText || (y.safeYieldM3PerH + ' m³/h'),
            'projected to ' + y.designPeriodDays + ' days, safety factor ' +
            y.safetyFactor),
          S.stat('Transmissivity', y.transmissivity + ' m²/day', 'preferred method'),
          S.stat('Pump intake', intakeM + ' m', 'below the top of the casing' +
            (intakeMoved ? ', moved to plain casing from the ' + y.pumpDepthM +
              ' m the yield recommendation asked for' : '')),
          S.stat('Specific capacity', y.specificCapacity + ' m³/h per m'),
        ]),
        y.methods && y.methods.length ? S.table([
          { key: 'label', label: 'Method' },
          { key: 'transmissivity', label: 'T (m²/day)', align: 'right' },
        ], y.methods.concat([
          { label: 'Preferred', transmissivity: y.transmissivity },
        ])) : null,
        el('p.muted', y.basis + (y.envelopeBasis ? ' ' + y.envelopeBasis : '')),
      ]),

      card('Design basis', [
        design.basis.length
          ? el('ul', design.basis.map(function (b) { return el('li', b); }))
          : el('p.muted', 'No basis recorded.'),
      ]),

      card('Flags on this design', [
        flagList(design.flags, 'No flags raised on the design or the test.'),
      ]),

      signOffCard({
        stage: 'design', clean: clean,
        recommended: y.pending ? 'a pending yield' : (y.rangeText || 'the design'),
        acceptLabel: 'the design',
        writesTo: 'Accepting writes to the completion and pumping-test reports',
        overrideLabel: 'Certified safe yield', overrideUnit: 'm³/h',
        overrideStart: y.safeYieldM3PerH || 0, overrideStep: 0.01,
        formatOverride: function (n) { return n + ' m³/h'; },
      }),
    ];
  }

  function spineQualityStage(view) {
    var q = view.quality;
    var judged = q.rows.filter(function (r) { return r.status !== 'no_guideline'; });
    /* Only rows the toolkit actually graded and found compliant. Counting
     * every non-"exceeds" status as within limits put the unevaluable and
     * the unmeasured in the compliant column. */
    var within = judged.filter(function (r) {
      return r.status === 'within_limits' || r.status === 'below_detection';
    });
    var ungraded = judged.filter(function (r) {
      return r.status === 'indeterminate' || r.status === 'not_measured';
    });
    /* Driven by the verdict state, so an unevaluable panel can never be
     * signed off as "Complies". */
    var headline = {
      health_fail: 'Not suitable for drinking',
      national_fail: 'Fails the national standard',
      indeterminate: 'Not proven safe — results incomplete',
      aesthetic: 'Potable — acceptability exceeded',
      pass: 'Complies',
    }[q.verdictState] || 'Not proven safe — results incomplete';
    var clean = q.verdictState === 'pass';
    var cor = q.corrosivity;
    var spine = charts.guidelineSpine(q.rows);

    return [
      card('The sample', [
        S.statRow([
          S.stat('Sampled', q.sampleDate || '—', q.laboratory || ''),
          S.stat('Within limits', within.length + ' / ' + judged.length,
            ungraded.length ? ungraded.length + ' could not be graded' : ''),
          S.stat('Health exceedances',
            q.healthExceedances.length ? String(q.healthExceedances.length) : 'none'),
          q.ionic ? S.stat('Ionic balance', q.ionic.errorPercent + ' %',
            'against a ±5 % acceptance limit') : null,
          cor ? S.stat('Corrosivity', cor.classification) : null,
        ].filter(Boolean)),
        spine ? charts.figure(spine,
          'Every determinand as a multiple of its own binding limit',
          { filename: 'guideline_spine' }) : null,
        el('p.muted', 'Limits come from the toolkit\'s standards table — the ' +
          'WHO health-based guideline value, the WHO acceptability value and ' +
          'the national standard, whichever binds.'),
      ]),

      q.ionic ? card('Ionic balance', [
        S.statRow([
          S.stat('Σ cations', q.ionic.cationsMeq + ' meq/L'),
          S.stat('Σ anions', q.ionic.anionsMeq + ' meq/L'),
          S.stat('Error', (q.ionic.errorPercent > 0 ? '+' : '') +
            q.ionic.errorPercent + ' %'),
        ]),
        el('p.muted', Math.abs(q.ionic.errorPercent) <= 5
          ? 'The analysis is internally consistent, so the rest of this page ' +
            'can be relied on.'
          : 'The analysis does not balance; treat every figure here with caution.'),
        q.ionic.usedAlkalinity
          ? el('p.muted', 'Bicarbonate was inferred from alkalinity.') : null,
      ]) : null,

      cor ? card('Corrosivity indices', [
        S.table([
          { key: '0', label: 'Index' }, { key: '1', label: 'Value' },
        ], [
          ['Langelier (LSI)', cor.lsi], ['Ryznar (RSI)', cor.rsi],
          ['Aggressive index', cor.aggressiveIndex],
          ['Larson-Skold', cor.larsonSkold],
          ['Classification', cor.classification],
        ]),
        /* Not "Handpump materials": the note underneath is about the rising
         * main and the wetted metal parts of whatever pump goes in, which on
         * a motorised installation is a pump nobody would call a handpump. */
        el('div.callout' + (cor.isAggressive ? '.callout-warn' : '.callout-ok'), [
          el('p', el('strong', 'Pump and rising main materials')),
          el('p', cor.materialsNote || cor.verdict),
        ]),
        cor.assumptions.length
          ? el('p.muted', cor.assumptions.join(' ')) : null,
      ]) : null,

      q.piper ? card('Hydrochemical facies', [
        /* A Piper diagram on its own tells a reader who cannot read one
         * nothing at all, which is what this card used to be. faciesOf names
         * the water type and says what it means, as the quality report now
         * does above the same figures. */
        faciesSentence(derived.sample),
        el('div.grid.grid-2', [
          charts.figure(charts.piper([derived.sample]), 'Piper diagram',
            { filename: 'piper' }),
          charts.figure(charts.stiff(derived.sample), 'Stiff diagram',
            { filename: 'stiff' }),
        ]),
      ].filter(Boolean)) : null,

      card('Exceedances', [
        S.table([
          { key: '0', label: 'Against' },
          { key: '1', label: 'Parameters' },
        ], [
          ['Health-based', q.healthExceedances.join(', ') || 'none'],
          ['National standard', q.nationalExceedances.join(', ') || 'none'],
          ['Acceptability', q.aestheticExceedances.join(', ') || 'none'],
        ]),
        el('p', q.verdict),
        q.wqi ? el('p.muted', 'Water quality index ' + q.wqi.value +
          ' — ' + q.wqi.rating + '.') : null,
        q.nationalExceedances.length ? provisionalStandardsNote() : null,
      ].filter(Boolean)),

      card('Flags on this analysis', [
        flagList(q.flags, 'No flags raised on the sample.'),
      ]),

      signOffCard({
        stage: 'quality', clean: clean, recommended: headline,
        acceptLabel: 'the verdict',
        writesTo: 'Accepting writes to the water-quality and handover reports',
        overrideLabel: 'Certified verdict', overrideUnit: '',
        overrideStart: headline,
        overrideChoices: ['Complies', 'Potable — acceptability exceeded',
          'Potable after treatment', 'Not proven safe — results incomplete',
          'Fails the national standard', 'Not suitable for drinking'],
      }),
    ].filter(Boolean);
  }

  function spineCostingStage(view) {
    var c = view.costing;
    var stages = [];
    c.items.forEach(function (i) {
      if (stages.indexOf(i.stage) < 0) stages.push(i.stage);
    });

    /* the lines the design drives, so the analyst can see what moved with it */
    var designDriven = /casing|screen|gravel|grout|seal|drill/i;
    var boqRows = [];
    stages.forEach(function (stageName) {
      var lines = c.items.filter(function (i) { return i.stage === stageName; });
      var subtotal = lines.reduce(function (a, l) { return a + l.amount; }, 0);
      boqRows.push({ item: stageName, subtotal: true, amount: subtotal });
      lines.forEach(function (line) {
        boqRows.push({
          item: line.item, unit: line.unit, quantity: line.quantity,
          unitCost: line.unitCost, amount: line.amount,
          derived: designDriven.test(line.item), note: line.note,
        });
      });
    });

    return [
      card('What it costs', [
        S.statRow([
          S.stat('Direct cost', S.money(c.directCost, 0)),
          S.stat('Cost to build', S.money(c.totalCost, 0),
            'direct + ' + c.overheadsPercent + '% overheads'),
          S.stat('Price to client', S.money(c.price, 0),
            'cost + ' + c.marginPercent + '% margin'),
          S.stat('Per metre', S.money(c.costPerMetre, 0), 'cost basis'),
        ]),
        el('p.muted', 'RWSN Cost-Effective Boreholes: quantities come from the ' +
          'design on the section, and the contractor\'s cost is kept apart ' +
          'from the client\'s price.' +
          (c.contingencyPercent > 0 ? ' A ' + c.contingencyPercent +
            '% client-side contingency is shown separately on the Costing ' +
            'page, so the contract price stays honest.' : '')),
      ]),

      card('Bill of quantities', [
        S.table([
          { key: 'item', label: 'Item' },
          { key: 'unit', label: 'Unit' },
          { key: 'quantity', label: 'Quantity', align: 'right' },
          { key: 'unitCost', label: 'Unit cost (US$)', align: 'right',
            format: function (v) { return v === undefined ? '' : S.money(v, 2); } },
          { key: 'amount', label: 'Amount (US$)', align: 'right',
            format: function (v) { return S.money(v, 0); } },
        ], boqRows, {
          rowClass: function (row) { return row.subtotal ? 'row-warn' : ''; },
        }),
        el('p.muted', 'Quantities on the casing, screen, gravel pack, grout and ' +
          'drilling lines move with the screens on the section: both come from ' +
          'the same design object.'),
        c.assumptions.length ? el('div.section', [
          el('h4.section-title', 'Assumptions filled in where the design is silent'),
          el('ul', c.assumptions.map(function (a) { return el('li', a); })),
        ]) : null,
      ]),

      card('Where the money goes', [
        el('div.grid.grid-2', [
          S.section('By stage', S.table([
            { key: 'label', label: 'Stage' },
            { key: 'amount', label: 'US$', align: 'right',
              format: function (v) { return S.money(v, 0); } },
            { key: 'share', label: 'Share', align: 'right',
              format: function (v) { return v + '%'; } },
          ], c.byStage)),
          S.section('By resource category', S.table([
            { key: 'label', label: 'Category' },
            { key: 'amount', label: 'US$', align: 'right',
              format: function (v) { return S.money(v, 0); } },
            { key: 'share', label: 'Share', align: 'right',
              format: function (v) { return v + '%'; } },
          ], c.byCategory)),
        ]),
        S.section('Quantities from the design', S.table([
          { key: '0', label: 'Quantity' }, { key: '1', label: 'Value' },
        ], [
          ['Total depth', c.quantityBasis.totalDepthM + ' m'],
          ['Plain casing', c.quantityBasis.casingM + ' m'],
          ['Screen', c.quantityBasis.screenM + ' m'],
          ['Gravel pack interval', c.quantityBasis.gravelIntervalM + ' m'],
          ['Overburden', (c.quantityBasis.overburdenM === null
            ? '—' : c.quantityBasis.overburdenM + ' m')],
        ])),
      ]),

      card('Flags on this estimate', [
        flagList(c.flags, 'No flags raised on the estimate.'),
      ]),

      signOffCard({
        stage: 'costing',
        clean: c.flags.every(function (f) { return f.level === 'info'; }),
        recommended: S.money(c.price, 0),
        acceptLabel: 'the price',
        writesTo: 'Accepting writes to the cost estimate and the bill of quantities',
        overrideLabel: 'Price to client', overrideUnit: 'US$',
        overrideStart: Math.round(c.price), overrideStep: 50,
        formatOverride: function (n) { return S.money(n, 0); },
      }),
    ];
  }

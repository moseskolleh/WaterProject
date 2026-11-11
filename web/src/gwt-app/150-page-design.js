
  /* --- borehole design ------------------------------------------------------ */

  PAGES.design = function () {
    var custom = store.get('design');
    var interp = bestInterpretation();
    var nodes = [
      pageHead('Borehole design', 'Screens against the aquifer and below the ' +
        'static level, plain casing, a sump, gravel pack, backfill and a cement ' +
        'sanitary seal — assembled by the rules in Settings and drawn to scale. ' +
        'When the log records the screens installed, the drawing is an as-built ' +
        'record instead of a design.'),
    ];

    var suggestedDepth = (derived.log && derived.log.total_depth_m) ||
      (interp && interp.max_drilling_depth_m) || null;

    nodes.push(card('Design inputs', [
      el('div.field-row', [
        field('Total depth (m)', S.numberInput(
          custom.totalDepth !== null && custom.totalDepth !== undefined
            ? custom.totalDepth : suggestedDepth,
          function (v) { store.set('design.totalDepth', v); rebuildDesign(); rebuildCosting(); render(); }),
          derived.log && derived.log.total_depth_m
            ? 'from the drilling log'
            : (interp ? 'from the VES recommendation' : 'enter the drilled depth')),
        field('Static water level (m)', S.numberInput(
          derived.test ? derived.test.static_water_level_m : null,
          function () {}, { disabled: true }),
          'from the pumping test sheet'),
        field('Pump intake (m)', S.numberInput(
          custom.pumpIntake !== null && custom.pumpIntake !== undefined
            ? custom.pumpIntake : recommendedIntake()[0],
          function (v) { store.set('design.pumpIntake', v); rebuildDesign(); render(); }),
          'from the yield recommendation unless overridden'),
      ]),
      uploadZone('drilling', 'Drilling log (.xlsx)',
        'Optional — screens follow the logged water strikes when present'),
    ]));

    if (!derived.design) {
      nodes.push(S.empty('A total depth is needed before a design can be ' +
        'assembled — from a drilling log, a VES interpretation, or typed above.'));
      return nodes;
    }

    var design = derived.design;
    /* The drawing is an as-built record only when the log records the
     * screens the crew set (design.as_built); otherwise the rules generated
     * it from the log and the page says so instead of calling it as-built.
     * The diameters, the annular fill and the pump intake are read off the
     * design object: the drilled diameter is the log's where it records one,
     * the fill follows the annulus (a 19 mm annulus carries no gravel pack)
     * and the intake may have been moved out of a screen into plain casing. */
    var drawingTitle = design.as_built ? 'As-built borehole record'
      : 'Borehole construction design';
    var diameterLogged = !!(derived.log && (derived.log.intervals || []).some(
      function (iv) { return iv.bit_diameter_in; }));
    var hasIntake = design.pump_intake_m !== null && design.pump_intake_m !== undefined;
    nodes.push(card(design.as_built ? 'Construction (as built)' : 'Construction', [
      S.statRow([
        S.stat('Total depth', C.fmtNum(design.total_depth_m) + ' m'),
        S.stat(design.as_built ? 'Screen (as installed)' : 'Screen',
          C.fmtNum(design.total_screen_length_m) + ' m',
          design.screens.length + ' ' +
          S.plural(design.screens.length, 'section') + ', slot ' +
          C.fmtNum(design.screen_slot_mm) + ' mm'),
        S.stat('Casing', C.formatG(design.casing_diameter_in) + '" ' +
          design.casing_material,
          'in a ' + C.formatG(design.borehole_diameter_in) + '" hole' +
          (diameterLogged ? ' as logged' : '')),
        S.stat('Annular fill', C.formatG(design.gravel_pack[0]) + '–' +
          C.formatG(design.gravel_pack[1]) + ' m', design.annular_fill_label),
        hasIntake ? S.stat('Pump intake', C.formatG(design.pump_intake_m) + ' m',
          'below the top of the casing') : null,
      ].filter(Boolean)),
      /* every flag the design raised, warnings and errors included: the thin
       * annulus and the moved pump intake used to reach no page */
      design.flags.length ? flagList(design.flags) : null,
      el('div.split', [
        el('div', [
          charts.figure(charts.boreholeDesign(design, derived.log),
            drawingTitle, { filename: design.as_built ? 'as_built_record'
              : 'borehole_design' }),
          el('p.muted', design.construction_note),
        ]),
        el('div', [
          S.table([
            { key: '0', label: 'Item' }, { key: '1', label: 'Detail' },
          ], C.designSummaryRows(design).map(function (row) {
            return { 0: row[0], 1: row[1] };
          })),
          el('h4', 'Design basis'),
          el('ul', design.design_basis.map(function (b) { return el('li', b); })),
        ]),
      ]),
    ]));

    var risingMain = risingMainCard(design);
    if (risingMain) nodes.push(risingMain);

    nodes.push(card('Screen placement', [
      el('p.muted', 'Screens are placed automatically against the water strikes ' +
        'in the drilling log, the aquifer intervals in the lithology, or the ' +
        'low resistivity zones of the VES interpretation. Override them here ' +
        'when the driller\'s judgement on site differs; an analyst-placed ' +
        'screen is validated by exactly the same checks.'),
      S.editableTable([
        { key: 'top', label: 'Top (m)', type: 'number' },
        { key: 'bottom', label: 'Bottom (m)', type: 'number' },
      ], (custom.screens
        /* the store holds [top, bottom] pairs, which is what the engine and
         * the Depth Spine both write; the table reads named columns, and
         * feeding it the raw pairs rendered every edited screen blank and
         * then wiped it on the next keystroke */
        ? custom.screens.map(function (pair) {
          return { top: pair[0], bottom: pair[1] };
        })
        : design.screens.map(function (s) {
          return { top: s.top_m, bottom: s.bottom_m };
        })), function (rows) {
        var screens = rows.filter(function (r) {
          return S.isNum(r.top) && S.isNum(r.bottom) && r.bottom > r.top;
        }).map(function (r) { return [r.top, r.bottom]; });
        store.set('design.screens', screens.length ? screens : null);
        rebuildDesign(); rebuildCosting();
      }, { addLabel: '+ Add screen interval' }),
      button('Reset to automatic placement', function () {
        store.set('design.screens', null); rebuildDesign(); rebuildCosting(); render();
      }, { variant: 'ghost' }),
    ]));

    nodes.push(reportCard('Borehole completion report', 'completion',
      'Introduction, methodology, drilling record, the borehole log table and ' +
      (design.as_built ? 'the as-built construction.'
        : 'the borehole construction design generated from the drilling log.')));
    nodes.push(nextStep('Next, analyse the pumping test to get a yield.',
      'Pumping test', 'pumping'));
    return nodes;
  };

  /* What the design specifies for the rising main, how often it is inspected,
   * and why: the water quality sample's corrosivity indices and pH (PLAN.md
   * step 7.2, C.risingMainChoice). The Streamlit app's design page shows the
   * same card. */
  function risingMainCard(design) {
    var choice = design.rising_main;
    if (!choice) return null;
    return card('Rising main', [
      S.statRow([
        S.stat('Rising main', choice.material, choice.upgraded
          ? 'in place of the ' + choice.standard + ' one the handpump line includes'
          : 'the one the handpump line includes'),
        S.stat('Rising main inspection', 'every ' + C.formatG(choice.inspection_months) +
          ' months'),
      ]),
      /* aggressive water, or water nobody has analysed, is a warning */
      el('div.callout' + (choice.chemistry === 'not_aggressive' ? '.callout-ok'
        : '.callout-warn'), el('p', choice.statement)),
      el('p.muted', (choice.upgraded
        ? 'The Costing page prices it as a line extra over the handpump, over ' +
          'the pump intake depth (over the whole depth where no intake is ' +
          'known). ' : '') +
        'Load or change the sample on the Water quality page and the design ' +
        'follows it.'),
    ]);
  }

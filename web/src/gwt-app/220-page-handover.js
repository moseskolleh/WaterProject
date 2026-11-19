
  /* --- handover ------------------------------------------------------------- */

  PAGES.handover = function () {
    var handover = store.get('handover');
    var nodes = [
      pageHead('Handover', 'The document the community and the district water ' +
        'office keep: what was built, what it yields, whether the water is safe ' +
        'and how to look after it.'),
      card('Handover details', [
        el('div.field-row', [
          field('Handover date', S.textInput(handover.date, function (v) {
            store.set('handover.date', v);
          })),
          /* The handover report's maintenance section follows this: a
           * submersible or solar pump has no rods to tighten and no strokes
           * to count, and the community used to be handed handpump care
           * whatever was installed. Left blank it asserts nothing, and the
           * data sheet omits the row rather than naming a pump nobody
           * recorded. */
          field('Pump installed', S.textInput(handover.pumpType, function (v) {
            store.set('handover.pumpType', v);
          }), 'e.g. India Mark II, submersible, solar'),
          /* handoverReport prints a tariff arrangement the browser had no way
           * to set, so the paragraph was unreachable here and present in every
           * Python handover. */
          field('Tariff arrangement', S.textInput(handover.tariffNote, function (v) {
            store.set('handover.tariffNote', v);
          }), 'how the committee collects and holds the user fees'),
        ]),
        el('h4', 'Water and sanitation committee'),
        S.editableTable([
          { key: 'name', label: 'Name' },
          { key: 'role', label: 'Role' },
          { key: 'contact', label: 'Contact' },
        ], handover.committee || [], function (rows) {
          store.set('handover.committee', rows);
        }, { addLabel: '+ Add member' }),
      ]),
    ];

    var ready = [
      ['Borehole design', !!derived.design, 'design'],
      ['Pumping test', !!derived.analysis, 'pumping'],
      ['Water quality', !!derived.assessment, 'quality'],
    ];
    nodes.push(card('What the handover report will carry', [
      S.table([
        { key: 'item', label: 'Input' },
        { key: 'state', label: 'State',
          format: function (v) { return S.badge(v ? 'ready' : 'missing', v ? 'ok' : 'warn'); } },
        /* a heading only a screen reader reads: the column is its buttons */
        { key: 'action', label: el('span.sr-only', 'Go to its page') },
      ], ready.map(function (r) {
        return {
          item: r[0], state: r[1],
          action: r[1] ? '' : button('Go', function () { goto(r[2]); }, { variant: 'ghost' }),
        };
      })),
      el('p.muted', 'A missing input does not block the report; the section ' +
        'simply says what still has to be done.'),
    ]));

    nodes.push(photoCard('handover', 'Handover photographs'));
    nodes.push(photoCard('completion', 'Construction photographs'));
    nodes.push(reportCard('Project handover report', 'handover',
      'Project summary, works completed, the borehole data sheet, water quality, ' +
      'operation and maintenance guidance, the committee and the signature block.'));
    nodes.push(bundleCard());
    return nodes;
  };

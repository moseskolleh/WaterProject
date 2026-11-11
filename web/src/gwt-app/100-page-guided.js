
  /* --- guided start --------------------------------------------------------- */

  PAGES.guided = function () {
    var steps = [
      { key: 'site', label: 'Record the site', page: 'site',
        done: !!store.get('site.community'),
        note: 'Client, community, chiefdom, district and GPS. Every report ' +
          'header and every map comes from this.' },
      { key: 'ves', label: 'Site the borehole', page: 'ves',
        done: pageDone('ves'),
        note: 'Upload the VES sheet. The app inverts each sounding, interprets ' +
          'the layers and ranks the drilling targets.' },
      { key: 'design', label: 'Design the borehole', page: 'design',
        done: pageDone('design'),
        note: 'Screens against the aquifer, casing, gravel pack and sanitary ' +
          'seal, drawn to scale.' },
      { key: 'pumping', label: 'Test the borehole', page: 'pumping',
        done: pageDone('pumping'),
        note: 'Cooper-Jacob, Theis and recovery, then a safe yield and a pump ' +
          'setting depth.' },
      { key: 'quality', label: 'Check the water', page: 'quality',
        done: pageDone('quality'),
        note: 'WHO and national limits, ionic balance, corrosivity and the ' +
          'Piper and Stiff diagrams.' },
      { key: 'costing', label: 'Cost the works', page: 'costing',
        done: pageDone('costing'),
        note: 'A bill of quantities on the RWSN model, with cost and price ' +
          'kept apart.' },
      { key: 'supervision', label: 'Supervise construction', page: 'supervision',
        done: pageDone('supervision'),
        note: 'Stage checklists and the numeric acceptance checks a supervisor ' +
          'applies on site.' },
      { key: 'handover', label: 'Hand over', page: 'handover',
        done: pageDone('handover'),
        note: 'The handover report, the data sheet and the operation and ' +
          'maintenance guidance for the community.' },
    ];
    var doneCount = steps.filter(function (s) { return s.done; }).length;

    return [
      pageHead('Guided start', 'Eight steps, in the order the work actually ' +
        'happens. Each one is a page you can also reach directly from the ' +
        'sidebar; this page just keeps the thread.'),
      card('Progress', [
        el('div.progress-track', el('div.progress-fill', {
          style: { width: (100 * doneCount / steps.length).toFixed(0) + '%' },
        })),
        el('p.muted.mt-s',
          doneCount + ' of ' + steps.length + ' steps complete'),
      ]),
      el('div', steps.map(function (step, i) {
        return card(null, [
          el('div.guided-step', [
            el('div.wizard-step' + (step.done ? '.done' : ''), [
              el('span.n', String(i + 1)),
            ]),
            el('div.guided-step-body', [
              el('h3', step.label),
              el('p.muted', step.note),
            ]),
            button(step.done ? 'Review' : 'Go', function () { goto(step.page); },
              { variant: step.done ? 'ghost' : undefined }),
          ]),
        ]);
      })),
    ];
  };

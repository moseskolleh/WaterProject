
  /* --- the field kit (PLAN.md step 2.5) --------------------------------------
   * Printed sheets for a crew with no device: one pumping test sheet for each
   * borehole named, and the three quick cards. The content is the engine's
   * (C.fieldKitContent, held to groundwater/field_kit.py by parity); the
   * Streamlit app builds the same kit on its Templates and Pumping test
   * pages. The boreholes typed in are kept for the session, not the project.
   * ---------------------------------------------------------------------- */

  var fieldKitDraft = null;

  function knownBoreholes() {
    var refs = [derived.log && derived.log.borehole_ref,
      derived.test && derived.test.borehole_ref].filter(Boolean);
    return refs.filter(function (ref, i) { return refs.indexOf(ref) === i; });
  }

  function fieldKitCard() {
    var box = /** @type {HTMLTextAreaElement} */ (el('textarea.input', {
      rows: 3, 'data-fieldkit': 'boreholes',
      placeholder: 'One borehole identifier a line, as the sheet should print it',
    }));
    box.value = fieldKitDraft === null ? knownBoreholes().join('\n') : fieldKitDraft;
    box.addEventListener('input', function () { fieldKitDraft = box.value; });
    var build = button('Field kit (.docx)', function (event) {
      buildFieldKit(box.value.split(/\r?\n/), event.target);
    });
    build.setAttribute('data-fieldkit', 'build');
    return card('Field kit', [
      el('p.muted', C.phrase('field_kit.about')),
      field('Boreholes', box),
      el('div.btn-row', [build]),
    ]);
  }

  async function buildFieldKit(boreholes, node) {
    var host = node ? node.closest('.card') : $('#page-host');
    var issued = null;
    try {
      await S.withBusy(host, 'Building the field kit…', async function () {
        await need(REPORT_BUNDLES);
        var cfg = config();
        var content = C.fieldKitContent(store.get('site'), boreholes, cfg);
        if (!content.sheets.length) {
          throw new Error('name at least one borehole, one a line.');
        }
        var builder = GWT.docx.fieldKit({
          style: cfg.style, content: content,
          symbols: content.sheets.map(function (sheet) {
            return qrDataUrl(sheet.payload, { ecc: 'H', scale: 8 });
          }),
          issue: issueFor('field_kit'),
        });
        var bytes = await builder.build();
        var name = 'field_kit_' + S.slug(content.project || siteLabel()) + '.docx';
        S.download(name, bytes);
        issued = recordIssue(builder.record, name, bytes);
      });
      S.toast('Field kit ready.' + codeWords(issued), 'ok');
    } catch (err) {
      S.toast('Could not build the field kit: ' + err.message, 'error');
    }
  }

  PAGES.templates = function () {
    return [
      pageHead('Templates', 'Blank workbooks in exactly the layout the readers ' +
        'expect. Fill one in the field, upload it, and every analysis follows.'),
      el('div.grid.grid-2', Object.keys(TEMPLATE_SPECS).map(function (key) {
        var spec = TEMPLATE_SPECS[key];
        return card(spec.label, [
          el('p.muted', spec.note),
          button('Download ' + spec.file, async function () {
            var bytes = await S.writeXlsx(spec.sheets());
            S.download(spec.file, new Blob([bytes]));
          }),
        ]);
      })),
      card('All of them at once', [
        button('Download every template (' +
          Object.keys(TEMPLATE_SPECS).length + ')', async function () {
          for (var key in TEMPLATE_SPECS) {
            if (!Object.prototype.hasOwnProperty.call(TEMPLATE_SPECS, key)) continue;
            var spec = TEMPLATE_SPECS[key];
            var bytes = await S.writeXlsx(spec.sheets());
            S.download(spec.file, new Blob([bytes]));
            await new Promise(function (r) { setTimeout(r, 250); });
          }
        }),
      ]),
      fieldKitCard(),
    ];
  };

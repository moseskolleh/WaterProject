
  /* --- scanned sheets ------------------------------------------------------- */

  var SCAN_MIME = {
    pdf: 'application/pdf', png: 'image/png', jpg: 'image/jpeg',
    jpeg: 'image/jpeg', webp: 'image/webp', gif: 'image/gif',
  };

  async function buildReviewWorkbook(document) {
    var bytes = await S.writeXlsx(C.reviewWorkbookSheets(document));
    var stem = String(document.source).replace(/\.[^.]+$/, '') || 'scan';
    S.download(stem + '_review.xlsx', new Blob([bytes]));
  }

  async function buildFilledVesTemplate(document) {
    var blank = TEMPLATE_SPECS.ves.sheets()[0];
    var rows = C.fillVesTemplateSheets(document, blank.rows);
    var bytes = await S.writeXlsx([{ name: 'VES 1', rows: rows }]);
    var stem = String(document.source).replace(/\.[^.]+$/, '') || 'scan';
    S.download(stem + '_ves_template.xlsx', new Blob([bytes]));
  }

  PAGES.extract = function () {
    var doc = derived.extraction;
    var apiKey = getApiKey();
    var nodes = [
      pageHead('Scanned sheets', 'A sheet that arrived as a PDF or a photograph, ' +
        'turned into the same records an uploaded template produces. A PDF with ' +
        'a text layer is read here in the page; a photograph has no text to ' +
        'read and goes to Claude. Uncertain values are highlighted in the ' +
        'review workbook, never silently accepted.'),
      card('Read a sheet', [
        el('p.muted', 'PDF, PNG, JPEG or WebP. Nothing is uploaded for the ' +
          'text-layer path — the whole PDF reader runs in this page.'),
        el('div.btn-row', [
          button('Read a text PDF', async function (event) {
            var file = await S.pickFile('.pdf,application/pdf');
            if (!file) return;
            var host = event.target.closest('.card');
            try {
              await S.withBusy(host, 'Reading the PDF…', async function () {
                var bytes = new Uint8Array(await S.readFile(file, 'arrayBuffer'));
                derived.extraction = await C.extractPdfText(bytes, file.name);
              });
              S.toast('Read a ' + derived.extraction.document_kind + ' sheet.', 'ok');
            } catch (e) {
              S.toast(e.message, 'error');
            }
            render();
          }),
          button('AI assisted extraction', async function (event) {
            if (!apiKey) {
              S.toast('Set an Anthropic API key on the Settings page first.', 'warn');
              goto('settings');
              return;
            }
            var file = await S.pickFile('.pdf,.png,.jpg,.jpeg,.webp');
            if (!file) return;
            var host = event.target.closest('.card');
            try {
              await S.withBusy(host, 'Transcribing the sheet with Claude…',
                async function () {
                  var bytes = new Uint8Array(await S.readFile(file, 'arrayBuffer'));
                  var extension = (file.name.split('.').pop() || '').toLowerCase();
                  derived.extraction = await C.extractWithClaude({
                    apiKey: apiKey,
                    model: store.get('extraction.model') || undefined,
                    base64: S.bytesToBase64(bytes),
                    mediaType: file.type || SCAN_MIME[extension] || 'application/pdf',
                    source: file.name,
                  });
                });
              S.toast('Transcribed a ' + derived.extraction.document_kind + ' sheet.', 'ok');
            } catch (e) {
              S.toast(e.message, 'error');
            }
            render();
          }, { variant: 'ghost' }),
          doc ? button('Clear', function () {
            derived.extraction = null; render();
          }, { variant: 'ghost' }) : null,
        ]),
        !apiKey ? el('p.muted', 'The AI path needs an Anthropic API key, set on ' +
          'the Settings page. It is the only feature here that sends anything ' +
          'anywhere, and it sends the sheet to Anthropic.') : null,
      ]),
    ];

    if (!doc) {
      nodes.push(S.empty('Nothing read yet. A field sheet printed from the ' +
        'templates carries a text layer and reads straight through; a photo of ' +
        'a handwritten sheet needs the AI path.'));
      return nodes;
    }

    var items = C.reviewItems(doc);
    nodes.push(card('What was read', [
      S.statRow([
        S.stat('Sheet type', doc.document_kind.replace(/_/g, ' ')),
        S.stat('Header fields', String(doc.header.length)),
        S.stat('Tables', String(doc.tables.length)),
        S.stat('To review', String(items.length),
          items.length ? 'checked by hand before use' : 'nothing flagged'),
      ]),
      el('p.muted', doc.notes + ' Extractor: ' + doc.extractor + '.'),
      el('div.btn-row', [
        button('Download review workbook (.xlsx)', async function () {
          try {
            await buildReviewWorkbook(doc);
          } catch (e) {
            S.toast('Could not write the review workbook: ' + e.message, 'error');
          }
        }),
        /* a table whose readings the template cannot take is not offered as
         * one: "Needs a human" says why */
        doc.document_kind === 'ves' && doc.tables.length &&
          !C.vesTemplateColumns(doc.tables[0]).missing.length
          ? button('Download filled VES template (.xlsx)', async function () {
            try {
              await buildFilledVesTemplate(doc);
            } catch (e) {
              S.toast('Could not write the VES template: ' + e.message, 'error');
            }
          }, { variant: 'ghost' }) : null,
      ]),
    ]));

    if (doc.header.length) {
      nodes.push(card('Header fields', [
        S.table([
          { key: 'name', label: 'Field' },
          { key: 'value', label: 'Value' },
          { key: 'confidence', label: 'Confidence', align: 'right',
            format: function (v) { return v.toFixed(2); } },
        ], doc.header, {
          rowClass: function (row) { return row.needs_review ? 'row-warn' : ''; },
        }),
      ]));
    }

    doc.tables.forEach(function (table, index) {
      nodes.push(card(table.title, [
        S.table(table.columns.map(function (column, i) {
          return { key: String(i), label: column || ('Column ' + (i + 1)) };
        }), table.rows, {
          rowClass: function (row, i) {
            return C.confidenceForRow(table, i) < C.REVIEW_THRESHOLD ? 'row-warn' : '';
          },
        }),
        el('p.muted', table.rows.length + ' ' + S.plural(table.rows.length, 'row') +
          ' read from table ' + (index + 1) + '.'),
      ]));
    });

    nodes.push(card('Needs a human', [
      items.length
        ? el('ul', items.map(function (item) { return el('li', item); }))
        : el('div.callout.callout-ok', el('p',
          'Nothing flagged: every value was read with high confidence. Spot ' +
          'check it anyway before it becomes a report.')),
      el('p.muted', 'Correct the flagged values in the review workbook, then ' +
        'upload the corrected sheet on the page that needs it. Extraction ' +
        'never writes into the project on its own.'),
    ]));
    nodes.push(nextStep('Blank templates for the field team are on the ' +
      'Templates page.', 'Templates', 'templates'));
    return nodes;
  };


  /* --- settings ------------------------------------------------------------- */

  PAGES.settings = function () {
    var cfg = config();
    function bindCfg(section, key) {
      return function (value) {
        store.set('config.' + section + '.' + key, value);
        /* a changed setting is a different key: the recompute inverts
         * again what the setting could change, and nothing else */
        inversionsStopped = false;
        recompute().then(refresh);
      };
    }
    function numberFields(section, keys) {
      return keys.map(function (spec) {
        return field(spec[1], S.numberInput(cfg[section][spec[0]],
          bindCfg(section, spec[0]), { step: 'any' }), spec[2]);
      });
    }

    return [
      pageHead('Settings', 'House style, interpretation thresholds and design ' +
        'rules. Every value is a project override of the toolkit default, so a ' +
        'client with different standards changes them here rather than in code.'),

      card('House style (reports and figures)', [
        el('div.field-row', [
          field('Organisation', S.textInput(cfg.style.organisation, function (v) {
            store.set('config.style.organisation', v); render();
          })),
          field('Organisation details', S.textInput(cfg.style.organisation_details,
            function (v) { store.set('config.style.organisation_details', v); render(); })),
          field('Report font', S.textInput(cfg.style.font_name, function (v) {
            store.set('config.style.font_name', v); render();
          })),
          field('Accent colour', S.textInput(cfg.style.accent_color, function (v) {
            store.set('config.style.accent_color', v); render();
          }), 'used for headings and table header rows'),
        ]),
      ]),

      card('VES interpretation thresholds (ohm-m)', [
        el('div.field-row', numberFields('ves', [
          ['fresh_basement_min_rho', 'Fresh basement, minimum'],
          ['laterite_min_rho', 'Dry laterite, minimum'],
          ['clay_max_rho', 'Clay, maximum'],
          ['max_layers', 'Maximum layers searched'],
          ['target_fit_percent', 'Target fit error (%)'],
          ['round_drilling_depth_to_m', 'Round drilling depth to (m)'],
        ])),
        el('p.muted', 'The defaults target crystalline basement terrain. Coastal ' +
          'sedimentary sites need different ranges.'),
      ]),

      card('Pumping test defaults', [
        el('div.field-row', numberFields('pumping', [
          ['safety_factor', 'Safety factor'],
          ['design_period_days', 'Design period (days)'],
          ['available_drawdown_fraction', 'Usable share of available drawdown'],
          ['pump_submergence_min_m', 'Minimum submergence (m)'],
          ['seasonal_allowance_m', 'Dry season decline allowance (m)'],
          ['cooper_jacob_u_max', 'Cooper-Jacob u limit'],
        ])),
      ]),

      card('Borehole design rules', [
        el('div.field-row', numberFields('design', [
          ['borehole_diameter_in', 'Drilled diameter (in)'],
          ['casing_diameter_in', 'Casing diameter (in)'],
          ['screen_slot_mm', 'Screen slot (mm)'],
          ['screen_length_default_m', 'Default screen length (m)'],
          ['sanitary_seal_depth_m', 'Sanitary seal depth (m)'],
          ['gravel_pack_above_top_screen_m', 'Gravel above top screen (m)'],
          ['sump_length_m', 'Sump length (m)'],
          ['stickup_m', 'Stick-up (m)'],
          ['min_screen_below_swl_m', 'Minimum screen depth below SWL (m)'],
        ])),
      ]),

      card('AI assisted extraction', [
        el('p.muted', 'Reading a photographed field sheet needs a model, and ' +
          'there is no server here to hold a key on your behalf. Paste an ' +
          'Anthropic API key to enable it on the Scanned sheets page.'),
        field('Anthropic API key',
          S.textInput(getApiKey(), function (value) {
            setApiKey(value, credential.remember);
            render();
          }, { type: 'password', autocomplete: 'off', spellcheck: 'false',
            placeholder: 'sk-ant-…' }),
          'Held for this tab only. It is never saved with your project and ' +
          'never written to this browser\'s long-term storage.'),
        S.checkboxInput(credential.remember,
          'Keep it for this tab (cleared when the tab closes). Leave ' +
          'unticked to hold it in memory only, so a page reload asks again.',
          function (checked) {
            setApiKey(getApiKey(), checked);
            render();
          }),
        field('Model',
          S.textInput(store.get('extraction.model') || '', function (value) {
            store.set('extraction.model', String(value).trim());
          }, { placeholder: C.EXTRACTION_MODEL }),
          'Leave blank for ' + C.EXTRACTION_MODEL + '.'),
        el('div.callout.callout-warn', el('p', [
          el('strong', 'A key in a browser is a key you have exposed. '),
          'The request goes from this page straight to api.anthropic.com, so ' +
          'the key is visible to anything running in this page. It is held ' +
          'for this tab only — never in long-term storage, never in a saved ' +
          'project file, never cached by the offline worker — but that ' +
          'removes durability, not exposure. Use a key scoped to this work ' +
          'and revoke it when the job is done. Every other page works ' +
          'without one. If you need this at scale, put the call behind your ' +
          'own server and keep the key there.',
        ])),
        getApiKey() ? el('div.btn-row', [
          button('Forget the key', function () {
            forgetApiKey();
            S.toast('The key was removed from this browser.', 'ok');
            render();
          }, { variant: 'ghost' }),
        ]) : null,
      ]),

      card('Project data', [
        el('div.btn-row', [
          button('Save project file', saveProject),
          button('Open project file', openProject, { variant: 'ghost' }),
          button('Reset everything', function () {
            /* the reports waiting on this phone (PLAN.md step 7.1) are in no
             * project file, so saving the project does not keep them */
            var queued = reportQueue().length, waiting = queued + heldReports().length;
            var asked = S.modal('Reset the workspace?', [el('p',
              'This clears the site details, the uploaded sheets, every result ' +
              'and the saved copy in this browser. Save the project first if you ' +
              'want to keep it.'), waiting ? el('p.reset-reports', 'It also deletes the ' +
              waiting + ' ' + S.plural(waiting, 'report') + ' from plates and by SMS ' +
              'waiting on this phone, which no project file carries.' + (queued
                ? ' Export the ones waiting on the Asset registry page first.' : '')) : null], [
              button('Reset', async function () {
                await store.forget();
                forgetApiKey();
                store.replace(blankState());
                Object.keys(derived).forEach(function (k) { derived[k] = null; });
                forgetTerrain();
                applyTheme(); renderChrome(); render();
                /* closed through its own close(), which hands the keyboard
                 * back to the page, and before the toast, which a dialog
                 * still open over the page could keep from being heard */
                asked.close();
                S.toast('Workspace reset.', 'ok');
              }, { variant: 'danger' }),
            ]);
          }, { variant: 'ghost' }),
        ]),
        el('p.muted', 'The working session is mirrored into this browser\'s ' +
          'storage so a refresh never loses fieldwork. The project file is the ' +
          'record you keep and share.'),
      ]),

      card('Storage in this browser', storageSummary()),
    ];
  };

  /* Where the session is kept, how much room it takes, and whether the
   * browser has agreed to keep it. Read when the page is drawn; the figures
   * are the browser's own estimate for this site, not this project alone. */
  function storageSummary() {
    var host = el('div', el('p.muted', 'Reading this browser\'s storage…'));
    function megabytes(bytes) {
      return bytes >= 1e9 ? (bytes / 1e9).toFixed(1) + ' GB'
        : (bytes / 1e6).toFixed(1) + ' MB';
    }
    storage.estimate().then(function (info) {
      var lines = [];
      if (info.mode === 'none') {
        lines.push(el('p', 'This browser will not keep the session (' +
          ((storage.error && storage.error.message) || 'no IndexedDB') +
          '), so nothing is autosaved here. Save a project file before ' +
          'closing the tab.'));
      } else {
        lines.push(el('p', 'The session is kept in this browser\'s IndexedDB. ' +
          'Each workbook and photograph is stored once, as a file of its own, ' +
          'and a change writes only the part of the session it changed.'));
        if (info.role === 'reader') {
          lines.push(el('p', 'Another tab is the one saving it; this tab is not.'));
        }
      }
      if (info.usage !== null && info.quota) {
        lines.push(el('p', 'In use: ' + megabytes(info.usage) + ' of about ' +
          megabytes(info.quota) + ' this browser allows this site.'));
      }
      if (info.persisted === true) {
        lines.push(el('p', 'The browser has agreed to keep it until you clear ' +
          'it yourself.'));
      } else if (info.persisted === false) {
        lines.push(el('p.muted', 'The browser may clear it if the device runs ' +
          'short of space, as it can for any site it has not agreed to keep. ' +
          'The project file is the copy to rely on.'));
      }
      S.clear(host);
      S.append(host, lines);
    });
    return host;
  }

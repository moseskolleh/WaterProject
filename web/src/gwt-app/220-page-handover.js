
  /* --- handover ------------------------------------------------------------- */

  /* The community handover sheet (PLAN.md step 9.1). What it says is worked
   * out by C.communitySheetContent, which parity holds to the Python
   * engine's; this page gathers what that needs, shows what the sheet will
   * say before it is built, draws its picture and saves the document. */

  /* Whether the project rests on a bundled example: the handover report's
   * own readiness says so (the "field data" requirement), and a sheet built
   * from one says across its top that it is not about a real borehole, even
   * where that requirement was overridden to publish the example. */
  function onExampleData() {
    return (reportReadiness('handover').requirements || []).some(function (r) {
      return r.key === 'field_data' && (r.state === 'unmet' || r.state === 'overridden');
    });
  }

  /* The identifier the sheet names: the one typed on the card, else the one
   * the Asset registry holds for this project's borehole, as the Streamlit
   * app's box starts from it. */
  function sheetAssetId() {
    var typed = (store.get('handover') || {}).assetId;
    if (typed) return typed;
    var held = store.get('asset');
    return held && held.asset_id ? String(held.asset_id) : '';
  }

  /* The language the sheet is printed in (PLAN.md step 9.2): the one chosen
   * on the card while this build still offers it, else English. A project
   * saved where a translation was installed opens in English where it is
   * not, rather than not at all. */
  function sheetLanguage() {
    var chosen = (store.get('handover') || {}).language || '';
    return C.textLanguages().some(function (l) { return l.code === chosen; }) ? chosen : '';
  }

  function communitySheetNow(cfg) {
    var handover = store.get('handover') || {};
    return C.communitySheetContent(store.get('site'), {
      analysis: derived.analysis || null, quality: derived.assessment || null,
      committee: handover.committee || [], assetId: sheetAssetId(),
      hoursPerDay: typeof handover.hoursPerDay === 'number' ? handover.hoursPerDay : null,
      example: onExampleData(), config: cfg, language: sheetLanguage(),
    });
  }

  /* text broken at spaces into lines of at most width characters, as
   * reporting/community_sheet.py wrap_words breaks it */
  function wrapWords(text, width) {
    var lines = [];
    String(text).split(' ').forEach(function (word) {
      var last = lines.length - 1;
      if (lines.length && lines[last].length + 1 + word.length <= width) lines[last] += ' ' + word;
      else lines.push(word);
    });
    return lines;
  }

  /* The sheet's picture, drawn as reporting/community_sheet.py sheet_picture
   * draws it, to the same measurements in centimetres: on the left the
   * rings, each with its distance; beside them the key, what is to be kept
   * beyond each ring; and on the right, where the sheet carries a link to
   * the report page, the square to scan with its label. Returns {image,
   * widthCm} for GWT.docx.communitySheet. */
  function communitySheetPicture(content) {
    var keep = content.keep_away, report = content.report, rings = keep.rings;
    var PX = 80;   /* pixels to a centimetre: about 200 to the inch */
    var widthCm = report.payload ? 16.0 : 12.6, heightCm = 5.0;
    var ink = '#161a17', ground = '#f1f3f0', accent = '#1b7a2e';
    var canvas = document.createElement('canvas');
    canvas.width = Math.round(widthCm * PX);
    canvas.height = Math.round(heightCm * PX);
    var ctx = canvas.getContext('2d');
    /* centimetres from the left and from the foot, as the Python draws */
    function X(cm) { return cm * PX; }
    function Y(cm) { return (heightCm - cm) * PX; }
    function face(points, bold) {
      ctx.font = (bold ? 'bold ' : '') + (points / 72 * 2.54 * PX).toFixed(1) +
        'px system-ui, -apple-system, "Segoe UI", Arial, sans-serif';
    }
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    var cx = 2.5, cy = heightCm / 2, step = 2.2 / Math.max(rings.length, 1);
    ctx.lineWidth = 2.5;
    ctx.strokeStyle = ink;
    /* outermost first, so that each ring is drawn over the one beyond it */
    for (var k = rings.length; k >= 1; k -= 1) {
      ctx.beginPath();
      ctx.arc(X(cx), Y(cy), k * step * PX, 0, 2 * Math.PI);
      ctx.fillStyle = k % 2 ? ground : '#ffffff';
      ctx.fill();
      ctx.stroke();
    }
    /* Nothing in the picture is assumed to be as long as the English: every
     * word drawn is measured first, by the steps of
     * reporting/community_sheet.py (sheet_picture, key_layout,
     * label_layout). The English is drawn where it always was. */
    function wide(text, points, bold) {
      face(points, bold);
      return ctx.measureText(text).width / PX;
    }
    /** text broken at spaces into lines no wider than limit (fit_words) */
    function fitWords(text, limit, points) {
      var broken = [];
      String(text).split(' ').forEach(function (word) {
        var last = broken.length - 1;
        if (broken.length && wide(broken[last] + ' ' + word, points, false) <= limit) {
          broken[last] += ' ' + word;
        } else {
          broken.push(word);
        }
      });
      return broken;
    }
    /** How much smaller than its size the widest of some texts has to be
     * set to be no wider than limit (fit_scale): measured at the size it
     * will be drawn at, and again until it fits, because type is fitted to
     * the pixel grid and does not shrink in exact proportion. */
    function fitScale(texts, points, bold, limit, start) {
      var scale = start === undefined ? 1 : start;
      for (var turn = 0; turn < 8; turn += 1) {
        var widestNow = 0;
        for (var t = 0; t < texts.length; t += 1) {
          widestNow = Math.max(widestNow, wide(texts[t], points * scale, bold));
        }
        if (widestNow <= limit * (1 + 1e-9)) break;
        /* in proportion first, which is exact for type that shrinks evenly;
         * then a little under it each time, for type that does not */
        scale *= limit / widestNow * (turn === 0 ? 1 : 0.99);
      }
      return scale;
    }
    var distances = rings.map(function (ring) { return ring.label; });
    /* a distance wider than the picture has room for left of the rings'
     * centre is set smaller, all of them alike */
    var ringScale = fitScale(distances, 7, true, 2 * (cx - 0.1));
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    rings.forEach(function (ring, i) {
      /* the distance sits on its ring, at the foot, on a patch of white */
      face(7 * ringScale, true);
      var patch = ctx.measureText(ring.label).width + 0.12 * PX;
      var at = Y(cy - (i + 1) * step);
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(X(cx) - patch / 2, at - 0.15 * PX, patch, 0.3 * PX);
      ctx.fillStyle = ink;
      ctx.fillText(ring.label, X(cx), at);
    });
    ctx.beginPath();
    ctx.arc(X(cx), Y(cy), 0.13 * PX, 0, 2 * Math.PI);
    ctx.fillStyle = accent;
    ctx.fill();
    ctx.lineWidth = 1.5;
    ctx.stroke();
    /* the word at the centre: one wider than the innermost ring would be
     * struck through by it, so it is given a patch of white, and one wider
     * than the rings is set smaller */
    var centreScale = fitScale([keep.centre], 6.5, true, 2 * 2.2 - 0.2);
    var named = wide(keep.centre, 6.5 * centreScale, true);
    face(6.5 * centreScale, true);
    if (named > 2 * step) {
      var over = ctx.measureText(keep.centre).width + 0.12 * PX;
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(X(cx) - over / 2, Y(cy + 0.22 + 0.24), over, 0.3 * PX);
    }
    ctx.fillStyle = ink;
    ctx.textBaseline = 'alphabetic';
    ctx.fillText(keep.centre, X(cx), Y(cy + 0.22));

    /* The key: one entry a ring, nearest first, each thing on its own line.
     * The rows start after the widest distance, a distance with a long word
     * for its unit is set smaller rather than left to push the rows off the
     * picture, a row too long for the room beside the rings is broken at its
     * spaces, and a key too tall, or with a word no line can hold, is set
     * closer and smaller. A translated row must not run under the square a
     * phone scans or off the edge. */
    var clear = 0.25, gapAfter = 0.1, labelMax = 2.2, pitchCm = 0.42;
    var labelScale = fitScale(distances, 8, true, labelMax);
    var widest = distances.reduce(function (w, label) {
      return Math.max(w, wide(label, 8 * labelScale, true));
    }, 0);
    var textAt = Math.max(7.3, 6.0 + widest + gapAfter);
    var limit = (report.payload ? 12.8 : widthCm) - clear - textAt;
    var rows = rings.map(function (ring) {
      return ring.what.map(function (what) { return fitWords(what, limit, 7.5); });
    });
    var lines = Math.max(rings.length - 1, 0) * 0.5, every = [];
    rows.forEach(function (things) {
      things.forEach(function (broken) {
        lines += broken.length;
        broken.forEach(function (line) { every.push(line); });
      });
    });
    var scale = fitScale(every, 7.5, false, limit,
      Math.min(1, lines ? (heightCm - 0.4) / (lines * pitchCm) : 1));
    var pitch = pitchCm * scale;
    var y = heightCm / 2 + lines * pitch / 2 - 0.2 * scale;
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    rings.forEach(function (ring, i) {
      face(8 * labelScale * scale, true);
      ctx.fillText(ring.label, X(6.0), Y(y));
      face(7.5 * scale, false);
      rows[i].forEach(function (broken) {
        broken.forEach(function (line) {
          ctx.fillText(line, X(textAt), Y(y));
          y -= pitch;
        });
      });
      y -= pitch / 2;
    });

    if (report.payload) {
      var code = C.qrEncode(report.payload, { ecc: 'H' });
      var size = code.size, side = 2.9, left = 12.8, top = heightCm - 0.35;
      var cell = side / (size + 2);   /* a module of white all round */
      ctx.fillStyle = '#000000';
      for (var r = 0; r < size; r += 1) {
        for (var c = 0; c < size; c += 1) {
          if (code.modules[r][c]) {
            /* from this module's edge to the next one's, in whole pixels:
             * neighbours abut exactly, with no white line between two dark
             * ones and no dark run into a light one. A module a pixel or two
             * too wide was a square that phones could not read. */
            var x0 = Math.floor(X(left + (c + 1) * cell)), x1 = Math.floor(X(left + (c + 2) * cell));
            var y0 = Math.floor(Y(top - (r + 1) * cell)), y1 = Math.floor(Y(top - (r + 2) * cell));
            ctx.fillRect(x0, y0, x1 - x0, y1 - y0);
          }
        }
      }
      /* the label's lines keep to the room under the square: more of them
       * than the English has are set closer */
      /* broken as the English always was, at 24 characters; then a line
       * still wider than the room under the square is broken again by its
       * measure, and a word no line can hold sets the label smaller */
      var room = 3.3, label = [];
      wrapWords(report.caption, 24).forEach(function (line) {
        (wide(line, 6.5, false) > room ? fitWords(line, room, 6.5) : [line])
          .forEach(function (part) { label.push(part); });
      });
      var foot = top - side - 0.25;
      var between = Math.min(0.33, (foot - 0.15) / Math.max(label.length - 1, 1));
      face(6.5 * Math.min(1, between / 0.33 + 0.15) * fitScale(label, 6.5, false, room), false);
      ctx.fillStyle = ink;
      ctx.textAlign = 'center';
      label.forEach(function (line, n) {
        ctx.fillText(line, X(left + side / 2), Y(foot - n * between));
      });
    }
    return { image: { dataUrl: canvas.toDataURL('image/png'), mime: 'image/png',
      width: canvas.width, height: canvas.height }, widthCm: widthCm,
      /* how the key was laid out, as key_layout returns it, with the room a
       * row had: for whoever checks the picture, as the browser suite does */
      key: { textAt: textAt, labelScale: labelScale, scale: scale, limit: limit, rows: rows,
        /* the distance column: how wide the widest is as drawn */
        labelWidth: widest,
        /* each line of each row, as wide as it is drawn */
        widths: rows.map(function (things) {
          return things.map(function (broken) {
            return broken.map(function (line) { return wide(line, 7.5 * scale, false); });
          });
        }) } };
  }

  async function buildCommunitySheet(node) {
    var host = node ? node.closest('.card') : $('#page-host');
    var issued = null;
    try {
      await S.withBusy(host, 'Building the community sheet…', async function () {
        await need(REPORT_BUNDLES);
        var cfg = config();
        var content = communitySheetNow(cfg);
        var builder = GWT.docx.communitySheet({
          style: cfg.style, content: content, picture: communitySheetPicture(content),
          issue: issueFor('community_sheet'),
        });
        var bytes = await builder.build();
        /* a sheet in another language is a file of its own beside the
         * English one */
        var name = 'community_sheet_' + S.slug(siteLabel()) +
          (content.language.code ? '_' + content.language.code : '') + '.docx';
        S.download(name, bytes);
        issued = recordIssue(builder.record, name, bytes);
      });
      S.toast('Community sheet ready.' + codeWords(issued), 'ok');
    } catch (err) {
      S.toast('Could not build the community sheet: ' + err.message, 'error');
    }
  }

  function communitySheetCard() {
    var handover = store.get('handover') || {};
    /* what the sheet will say, as things stand */
    function said() {
      try {
        var content = communitySheetNow(config());
        return [
          el('h4', 'What the sheet will say'),
          content.example ? el('div.callout.callout-warn', el('p', content.example)) : null,
          el('ul', [el('li', content.water.headline), el('li', content.quality.headline)]),
          el('h4', 'What it could not say, and why'),
          el('ul.muted', content.notes.map(function (note) { return el('li', note); })),
        ];
      } catch (err) {
        /* a report address the registry will not print on a plate, or a
         * link too long for the square */
        return [el('div.callout.callout-bad', el('p', err.message))];
      }
    }
    /* Only this part is drawn again when a box changes. Drawing the whole
     * page again took the other box out from under the pointer that had
     * just left this one, and with it whatever was typed there next. */
    var saying = el('div', { 'aria-live': 'polite' }, said());
    function say() {
      S.clear(saying);
      S.append(saying, said());
    }
    /* The choice of language is offered only where a translation is: one
     * that names who translated it and who checked it, and has no fault
     * (C.textLanguages). With none, the sheet is English and says so. */
    var offered = C.textLanguages();
    return card('Community handover sheet', [
      el('p.muted', C.phrase('community_sheet.about')),
      el('div.field-row', [
        field('Hours the pump is used each day', S.numberInput(handover.hoursPerDay, function (v) {
          store.set('handover.hoursPerDay', v);
          say();
        }, { min: 0, max: 24, step: 0.5 }), 'for the amount of water in a day'),
        field('Borehole identifier', S.textInput(sheetAssetId(), function (v) {
          store.set('handover.assetId', String(v).trim());
          say();
        }), 'as on its plate, from the Asset registry'),
        offered.length ? field('Language of the sheet', S.selectInput(sheetLanguage(),
          [{ value: '', label: 'English' }].concat(offered.map(function (l) {
            /* two translations of one name are told apart by their codes */
            var twice = offered.filter(function (o) { return o.name === l.name; }).length > 1;
            return { value: l.code, label: twice ? l.name + ' (' + l.code + ')' : l.name };
          })), function (v) {
            store.set('handover.language', v);
            say();
          }), 'what the translation has no words for is printed in English') : null,
      ]),
      saying,
      el('div.btn-row', [
        button('Community sheet (.docx)', function (event) {
          buildCommunitySheet(event && event.currentTarget);
        }),
      ]),
    ]);
  }

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
    nodes.push(communitySheetCard());
    nodes.push(bundleCard());
    return nodes;
  };

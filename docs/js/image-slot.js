/* image-slot.js - photo slots for the report figures.
 *
 * Field teams arrive with phone photos: the completed headworks, the pump test
 * in progress, the drill cuttings laid out, the handover ceremony. Each report
 * has named places those belong. A slot takes a picture by drag, by file
 * picker or by paste, downscales it in the browser, keeps a caption with it and
 * hands the bytes to the .docx writer.
 *
 * Nothing is uploaded anywhere: the image never leaves the machine, it lives in
 * the project state and travels inside the .gwt project file.
 */
(function (global) {
  'use strict';

  var GWT = global.GWT || (global.GWT = {});
  var S = GWT.support;
  var el = S.el, button = S.button;

  /* Phone cameras produce 4000 px, 6 MB frames. A report figure is printed
   * about 16 cm wide, so 1600 px is already more than the page can show, and
   * it keeps a project file with a dozen photos in the low megabytes. */
  var MAX_EDGE = 1600;
  var JPEG_QUALITY = 0.82;

  /* The named slots each report offers, in the order they are laid out. */
  var SLOT_SETS = {
    completion: [
      { key: 'site', label: 'Site before drilling',
        hint: 'The chosen spot with the community, for the record of where the mark was set' },
      { key: 'drilling', label: 'Drilling in progress' },
      { key: 'cuttings', label: 'Drill cuttings',
        hint: 'Laid out in depth order beside the metre marks' },
      { key: 'development', label: 'Development and test pumping' },
      { key: 'headworks', label: 'Completed headworks',
        hint: 'Apron, drainage channel and soakaway in one frame' },
      { key: 'pump', label: 'Installed pump' },
    ],
    quality: [
      { key: 'sampling', label: 'Sampling at the wellhead' },
      { key: 'appearance', label: 'Sample appearance',
        hint: 'Against a white background, for colour and turbidity' },
      { key: 'field_meter', label: 'Field meter reading' },
    ],
    pumping: [
      { key: 'setup', label: 'Test set-up',
        hint: 'Pump, dip meter, discharge measurement and stopwatch' },
      { key: 'discharge', label: 'Discharge measurement' },
      { key: 'disposal', label: 'Discharge disposal away from the borehole' },
    ],
    geophysical: [
      { key: 'survey', label: 'Survey in progress' },
      { key: 'terrain', label: 'Site and terrain' },
      { key: 'community', label: 'Community consultation' },
    ],
    supervision: [
      { key: 'materials', label: 'Materials on site',
        hint: 'Casing, screen and gravel as delivered, before installation' },
      { key: 'installation', label: 'Casing and screen installation' },
      { key: 'grouting', label: 'Sanitary seal being placed' },
      { key: 'nonconformance', label: 'Any non-conformance observed' },
    ],
    handover: [
      { key: 'ceremony', label: 'Handover to the community' },
      { key: 'committee', label: 'Water committee' },
      { key: 'plaque', label: 'Borehole plaque or marker' },
      { key: 'inuse', label: 'Source in use' },
    ],
  };

  /* ------------------------------------------------------------ scaling */

  function loadImage(src) {
    return new Promise(function (resolve, reject) {
      var img = new Image();
      img.onload = function () { resolve(img); };
      img.onerror = function () { reject(new Error('That file is not an image the browser can open.')); };
      img.src = src;
    });
  }

  /* Returns {dataUrl, width, height, mime, bytes} with the long edge capped. */
  async function shrink(file) {
    var dataUrl = await S.readFile(file, 'dataUrl');
    var img = await loadImage(dataUrl);
    var scale = Math.min(1, MAX_EDGE / Math.max(img.naturalWidth, img.naturalHeight));
    var w = Math.max(1, Math.round(img.naturalWidth * scale));
    var h = Math.max(1, Math.round(img.naturalHeight * scale));
    /* A PNG screenshot of a chart must stay a PNG: re-encoding line art as
     * JPEG smears the axis labels. Photographs go to JPEG. */
    var keepPng = /png/i.test(file.type || '') && (file.size < 900000 || scale === 1);
    var mime = keepPng ? 'image/png' : 'image/jpeg';
    if (scale === 1 && (file.size || 0) < 700000) {
      return {
        dataUrl: dataUrl, width: img.naturalWidth, height: img.naturalHeight,
        mime: file.type || mime, name: file.name || 'photo',
      };
    }
    var canvas = document.createElement('canvas');
    canvas.width = w; canvas.height = h;
    var ctx = canvas.getContext('2d');
    ctx.fillStyle = '#FFFFFF';
    ctx.fillRect(0, 0, w, h);
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(img, 0, 0, w, h);
    return {
      dataUrl: canvas.toDataURL(mime, JPEG_QUALITY),
      width: w, height: h, mime: mime, name: file.name || 'photo',
    };
  }

  function fileFromDrop(event) {
    var dt = event.dataTransfer;
    if (!dt) return null;
    var files = Array.prototype.slice.call(dt.files || []);
    return files.filter(function (f) { return /^image\//.test(f.type); })[0] || null;
  }

  /* ------------------------------------------------------------ the slot */

  /* create({key, label, hint, value, onChange}) -> DOM node.
   * value is {dataUrl, width, height, mime, caption} or null. */
  function create(spec) {
    var value = spec.value || null;
    var host = el('div.img-slot', { dataset: { key: spec.key || '' } });

    function emit() {
      if (spec.onChange) spec.onChange(value ? Object.assign({}, value) : null);
    }

    async function take(file) {
      if (!file) return;
      if (!/^image\//.test(file.type)) {
        S.toast('That file is not an image.', 'warn');
        return;
      }
      try {
        var shrunk = await shrink(file);
        value = Object.assign({ caption: (value && value.caption) || '' }, shrunk);
        emit();
        render();
      } catch (e) {
        S.toast(e.message || 'Could not read that image.', 'error');
      }
    }

    function render() {
      S.clear(host);
      var head = el('div.img-slot-head', [
        el('span.img-slot-label', spec.label || spec.key),
        value ? button('Remove', function () {
          value = null; emit(); render();
        }, { variant: 'ghost' }) : null,
      ]);

      var body;
      if (value) {
        body = el('div.img-slot-filled', [
          el('img.img-slot-preview', {
            src: value.dataUrl, alt: spec.label || '',
            onclick: function () {
              S.modal(spec.label || 'Photo', el('img.img-full', { src: value.dataUrl }));
            },
          }),
          el('div.img-slot-meta', [
            el('span', value.width + ' × ' + value.height + ' px'),
            button('Replace', function () {
              S.pickFile('image/*').then(take);
            }, { variant: 'ghost' }),
          ]),
          S.textInput(value.caption || '', function (v) {
            value.caption = v; emit();
          }, { class: 'input', placeholder: 'Caption printed under the figure' }),
        ]);
      } else {
        body = el('div.img-slot-drop', {
          tabindex: '0',
          onclick: function () { S.pickFile('image/*').then(take); },
          onkeydown: function (e) {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault(); S.pickFile('image/*').then(take);
            }
          },
        }, [
          el('span.img-slot-icon', '＋'),
          el('span.img-slot-hint', 'Drop a photo, click to choose, or paste'),
          spec.hint ? el('span.img-slot-note', spec.hint) : null,
        ]);
        body.addEventListener('dragover', function (e) {
          e.preventDefault(); body.classList.add('over');
        });
        body.addEventListener('dragleave', function () { body.classList.remove('over'); });
        body.addEventListener('drop', function (e) {
          e.preventDefault(); body.classList.remove('over');
          take(fileFromDrop(e));
        });
        /* Paste lands in whichever slot the user last focused. */
        body.addEventListener('focus', function () { activeSlot = take; });
        body.addEventListener('blur', function () {
          if (activeSlot === take) activeSlot = null;
        });
      }
      S.append(host, [head, body]);
    }

    render();
    return host;
  }

  /* One paste listener for the whole page; it feeds the focused empty slot. */
  var activeSlot = null;
  if (typeof document !== 'undefined') {
    document.addEventListener('paste', function (e) {
      if (!activeSlot) return;
      var items = Array.prototype.slice.call((e.clipboardData || {}).items || []);
      for (var i = 0; i < items.length; i++) {
        if (/^image\//.test(items[i].type)) {
          var file = items[i].getAsFile();
          if (file) { e.preventDefault(); activeSlot(file); return; }
        }
      }
    });
  }

  /* A whole named set, bound to store.photos[setName]. */
  function gallery(setName, values, onChange, options) {
    var opts = options || {};
    var slots = SLOT_SETS[setName] || [];
    var current = Object.assign({}, values || {});
    var extras = Array.isArray(current.__extra) ? current.__extra.slice() : [];

    function fire() {
      var out = Object.assign({}, current);
      out.__extra = extras;
      onChange(out);
    }

    var host = el('div.img-gallery');

    function render() {
      S.clear(host);
      var grid = el('div.img-grid', slots.map(function (slot) {
        return create({
          key: slot.key, label: slot.label, hint: slot.hint,
          value: current[slot.key],
          onChange: function (v) {
            if (v) current[slot.key] = v; else delete current[slot.key];
            fire();
          },
        });
      }).concat(extras.map(function (extra, i) {
        return create({
          key: 'extra_' + i, label: extra.label || ('Additional photo ' + (i + 1)),
          value: extra.image,
          onChange: function (v) {
            if (v) { extras[i].image = v; fire(); }
            else { extras.splice(i, 1); fire(); render(); }
          },
        });
      })));
      var foot = opts.allowExtra === false ? null : el('div.img-gallery-foot', [
        button('+ Another photo', function () {
          extras.push({ label: '', image: null });
          fire(); render();
        }, { variant: 'ghost' }),
        el('span.muted', countLabel()),
      ]);
      S.append(host, [grid, foot]);
    }

    function countLabel() {
      var n = slots.filter(function (s) { return current[s.key]; }).length +
        extras.filter(function (e) { return e.image; }).length;
      return n ? n + ' ' + S.plural(n, 'photo') + ' will be embedded in the report'
        : 'No photos yet — the report prints without a photo plate';
    }

    render();
    return host;
  }

  /* Everything a report writer needs: ordered, captioned, decoded. */
  function collect(values, setName) {
    var out = [];
    if (!values) return out;
    (SLOT_SETS[setName] || []).forEach(function (slot) {
      var v = values[slot.key];
      if (v && v.dataUrl) {
        out.push({
          key: slot.key, label: slot.label,
          caption: v.caption || slot.label,
          dataUrl: v.dataUrl, mime: v.mime || 'image/jpeg',
          width: v.width, height: v.height,
        });
      }
    });
    (values.__extra || []).forEach(function (extra, i) {
      if (extra && extra.image && extra.image.dataUrl) {
        out.push({
          key: 'extra_' + i, label: extra.label || 'Additional photo',
          caption: extra.image.caption || extra.label || 'Additional photo',
          dataUrl: extra.image.dataUrl, mime: extra.image.mime || 'image/jpeg',
          width: extra.image.width, height: extra.image.height,
        });
      }
    });
    return out;
  }

  function count(values, setName) {
    return collect(values, setName).length;
  }

  GWT.imageSlot = {
    create: create, gallery: gallery, collect: collect, count: count,
    shrink: shrink, sets: SLOT_SETS, MAX_EDGE: MAX_EDGE,
  };
}(typeof window !== 'undefined' ? window : globalThis));

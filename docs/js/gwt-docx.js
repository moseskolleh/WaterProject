/* gwt-docx.js - the house-styled .docx reports, written in the browser.
 *
 * A .docx is a ZIP of OOXML parts, so with a ZIP writer (support.js) the whole
 * report can be assembled client-side: no server, no library, and the file the
 * field team downloads never leaves their machine.
 *
 * The layout follows groundwater/reporting/docx_utils.py: A4 with 2.5 cm
 * margins, Calibri 11, accent-coloured headings, a shaded table header row,
 * numbered figure and table captions, page numbers in the footer and a
 * refreshable table of contents.
 */
(function (global) {
  'use strict';

  var GWT = global.GWT || (global.GWT = {});
  var S = GWT.support;
  var C = GWT.core;

  var EMU_PER_CM = 360000;
  var XML_HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n';
  var W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"' +
    ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"' +
    ' xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"' +
    ' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"' +
    ' xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"';

  function esc(text) { return S.escapeXml(text); }

  /* The reports are written from generated prose, so a stray control character
   * or a doubled space from string concatenation must not reach Word. */
  function clean(text) {
    return String(text === null || text === undefined ? '' : text)
      .replace(/\s+/g, ' ').trim();
  }

  /* ---------------------------------------------------------------- builder */

  function ReportBuilder(options) {
    var opts = options || {};
    var style = opts.style || C.defaultConfig().style;
    this.style = style;
    this.title = opts.title || 'Report';
    this.body = [];
    this.images = [];
    this.figureNo = 0;
    this.tableNo = 0;
    this.accent = String(style.accent_color || '#1F5C8B').replace('#', '');
    this.font = style.font_name || 'Calibri';
    this.baseSize = style.base_font_size_pt || 11;
    /* Set by provisionalStamp and read by executiveSummary, which used to
     * open with an unqualified verdict two pages after the stamp said the
     * evidence was incomplete. */
    this.stampedReadiness = null;
  }

  ReportBuilder.prototype.run = function (text, attrs) {
    var a = attrs || {};
    var props = '';
    if (a.bold) props += '<w:b/>';
    if (a.italic) props += '<w:i/>';
    if (a.size) props += '<w:sz w:val="' + Math.round(a.size * 2) + '"/>';
    if (a.color) props += '<w:color w:val="' + a.color.replace('#', '') + '"/>';
    if (a.font) props += '<w:rFonts w:ascii="' + esc(a.font) + '" w:hAnsi="' + esc(a.font) + '"/>';
    var rPr = props ? '<w:rPr>' + props + '</w:rPr>' : '';
    /* Cell values may carry newlines for stacked layer entries. */
    var parts = String(text === null || text === undefined ? '' : text).split('\n');
    var body = parts.map(function (part, i) {
      return (i ? '<w:br/>' : '') + '<w:t xml:space="preserve">' + esc(part) + '</w:t>';
    }).join('');
    return '<w:r>' + rPr + body + '</w:r>';
  };

  ReportBuilder.prototype.paragraph = function (text, attrs) {
    var a = attrs || {};
    var pPr = '';
    if (a.style) pPr += '<w:pStyle w:val="' + a.style + '"/>';
    if (a.align) {
      pPr += '<w:jc w:val="' + (a.align === 'justify' ? 'both' : a.align) + '"/>';
    }
    if (a.indentCm !== undefined) {
      pPr += '<w:ind w:left="' + Math.round(a.indentCm * 567) + '"' +
        (a.hangingCm ? ' w:hanging="' + Math.round(a.hangingCm * 567) + '"' : '') + '/>';
    }
    if (a.spaceAfter !== undefined) {
      pPr += '<w:spacing w:after="' + Math.round(a.spaceAfter * 20) + '"/>';
    }
    if (a.keepNext) pPr += '<w:keepNext/>';
    var body = a.raw !== undefined ? a.raw : this.run(clean(text), a);
    this.body.push('<w:p>' + (pPr ? '<w:pPr>' + pPr + '</w:pPr>' : '') + body + '</w:p>');
    return this;
  };

  ReportBuilder.prototype.heading = function (text, level) {
    var lvl = Math.min(Math.max(level || 1, 1), 3);
    this.paragraph(text, { style: 'Heading' + lvl, keepNext: true });
    return this;
  };

  ReportBuilder.prototype.bullets = function (items) {
    var self = this;
    (items || []).filter(Boolean).forEach(function (item) {
      self.paragraph(item, { style: 'ListBullet' });
    });
    return this;
  };

  ReportBuilder.prototype.spacer = function () {
    this.body.push('<w:p/>');
    return this;
  };

  ReportBuilder.prototype.pageBreak = function () {
    this.body.push('<w:p><w:r><w:br w:type="page"/></w:r></w:p>');
    return this;
  };

  /* Word fills this in on "Update Field"; the placeholder tells the reader so. */
  ReportBuilder.prototype.tableOfContents = function () {
    this.heading('Table of Contents', 1);
    this.body.push('<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>' +
      '<w:r><w:instrText xml:space="preserve"> TOC \\o "1-3" \\h \\z \\u </w:instrText></w:r>' +
      '<w:r><w:fldChar w:fldCharType="separate"/></w:r>' +
      '<w:r><w:t xml:space="preserve">Right-click and choose Update Field to fill ' +
      'the table of contents.</w:t></w:r>' +
      '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>');
    this.pageBreak();
    return this;
  };

  ReportBuilder.prototype.cover = function (titleLines, subtitleLines, details) {
    var self = this;
    if (this.style.organisation) {
      this.paragraph(this.style.organisation,
        { bold: true, size: 13, align: 'center', color: this.accent });
    }
    if (this.style.organisation_details) {
      this.paragraph(this.style.organisation_details, { size: 9, align: 'center' });
    }
    this.spacer(); this.spacer();
    (titleLines || []).forEach(function (line, i) {
      self.paragraph(line, {
        bold: true, size: i === 0 ? 20 : 15, align: 'center',
        color: i === 0 ? self.accent : null,
      });
    });
    (subtitleLines || []).forEach(function (line) {
      self.paragraph(line, { size: 12, align: 'center' });
    });
    this.spacer();
    /* A detail nobody filled in is left off rather than printed as a label
     * with nothing after it: the handover cover carried a bare "Project:"
     * and a bare "Date:", which read as two blank lines on the first page of
     * a signed document (docx_utils.ReportBuilder.cover). An em dash is how
     * the rest of this file writes "no value recorded", so it is as unfilled
     * here as an empty string. */
    var filled = (details || []).filter(function (pair) {
      var value = pair[1] === null || pair[1] === undefined ? '' : String(pair[1]).trim();
      return value !== '' && value !== '—';
    });
    if (filled.length) {
      this.keyValueTable(filled);
    }
    this.pageBreak();
    return this;
  };

  /* Say on the cover that this document is not a certification.
   *
   * A report is what a borehole is handed over on, so one built from
   * incomplete evidence must not be indistinguishable from one built from
   * complete evidence. A ready project gets no stamp; every other project
   * gets this, naming what is outstanding or what was overridden and by
   * whom, in the document itself rather than in a toast nobody keeps. */
  ReportBuilder.prototype.provisionalStamp = function (readiness) {
    if (!readiness || readiness.is_certifiable) return this;
    var self = this;
    /* remembered for the executive summary, which is two pages on and used
     * to give the verdict with no hint that the cover had qualified it */
    this.stampedReadiness = readiness;
    var overridden = readiness.state === 'ready_with_overrides';
    this.paragraph(overridden
      ? 'ISSUED ON OVERRIDE - NOT A CERTIFICATION'
      : 'PROVISIONAL - NOT FOR CERTIFICATION',
      { bold: true, size: 13, align: 'center', color: 'B23A2E' });
    this.paragraph(overridden
      ? 'This report was issued although the following requirements were not ' +
        'met. The reason recorded for each is given.'
      : 'This report rests on incomplete results. The following requirements ' +
        'for certification are outstanding.',
      { italic: true, align: 'justify' });
    var lines = [];
    (readiness.overridden || []).forEach(function (req) {
      var who = req.override_by ? ' (' + req.override_by + ')' : '';
      lines.push(req.title + ': ' + req.detail + ' Overridden' + who + ': ' +
        (req.override_reason || 'no reason recorded'));
    });
    (readiness.unmet || []).forEach(function (req) {
      lines.push(req.title + ': ' + req.detail);
    });
    if (lines.length) self.bullets(lines);
    this.pageBreak();
    return this;
  };

  ReportBuilder.prototype.executiveSummary = function (paragraphs, keyFindings) {
    var self = this;
    this.heading('Executive Summary', 1);
    /* The summary is qualified the way the cover is. A provisional stamp on
     * page one and an unhedged "the source is rated at ..." on page three is
     * a contradiction a reader who starts at the summary never sees resolved,
     * so the same qualification is repeated here, naming what is outstanding
     * or overridden (docx_utils.ReportBuilder.executive_summary). */
    var readiness = this.stampedReadiness;
    if (readiness && !readiness.is_certifiable) {
      var what = [];
      var outstanding = (readiness.unmet || []).map(function (req) { return req.title; });
      var overridden = (readiness.overridden || []).map(function (req) { return req.title; });
      if (outstanding.length) what.push('outstanding: ' + outstanding.join(', '));
      if (overridden.length) what.push('issued on override: ' + overridden.join(', '));
      this.paragraph('This report is provisional and not a certification (' +
        what.join('; ') + '). The findings below are those the supplied ' +
        'records support; the cover says what is missing.',
        { bold: true, align: 'justify' });
    }
    (paragraphs || []).filter(Boolean).forEach(function (text) {
      self.paragraph(text, { align: 'justify' });
    });
    if (keyFindings && keyFindings.filter(Boolean).length) {
      this.paragraph('Key findings:', { bold: true });
      this.bullets(keyFindings);
    }
    this.pageBreak();
    return this;
  };

  /* --- tables --------------------------------------------------------------- */

  ReportBuilder.prototype.table = function (rows, options) {
    var self = this;
    var opts = options || {};
    var header = opts.header || null;
    var fontSize = opts.fontSize || 9.5;
    var nCols = header ? header.length
      : rows.reduce(function (a, r) { return Math.max(a, r.length); }, 1);

    this.tableNo += 1;
    if (opts.caption) {
      this.paragraph('Table ' + this.tableNo + '. ' + clean(opts.caption),
        { bold: true, size: 9, keepNext: true });
    }

    var widths = opts.colWidthsCm;
    var grid = '<w:tblGrid>';
    for (var g = 0; g < nCols; g++) {
      var w = widths && widths[g] ? Math.round(widths[g] * 567) : Math.round(16000 / nCols);
      grid += '<w:gridCol w:w="' + w + '"/>';
    }
    grid += '</w:tblGrid>';

    var borders = '<w:tblBorders>' +
      ['top', 'left', 'bottom', 'right', 'insideH', 'insideV'].map(function (side) {
        return '<w:' + side + ' w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>';
      }).join('') + '</w:tblBorders>';

    var xml = '<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/>' +
      '<w:tblW w:w="0" w:type="auto"/><w:jc w:val="center"/>' + borders +
      '</w:tblPr>' + grid;

    function cell(text, cellOpts) {
      var co = cellOpts || {};
      var props = '<w:tcPr>';
      if (co.widthCm) props += '<w:tcW w:w="' + Math.round(co.widthCm * 567) + '" w:type="dxa"/>';
      if (co.fill) props += '<w:shd w:val="clear" w:color="auto" w:fill="' + co.fill + '"/>';
      props += '</w:tcPr>';
      var pPr = '<w:pPr><w:spacing w:after="20"/>' +
        (co.align ? '<w:jc w:val="' + co.align + '"/>' : '') + '</w:pPr>';
      return '<w:tc>' + props + '<w:p>' + pPr +
        self.run(text === null || text === undefined ? '' : String(text), {
          bold: co.bold, size: co.size || fontSize, color: co.color,
        }) + '</w:p></w:tc>';
    }

    if (header) {
      xml += '<w:tr><w:trPr><w:tblHeader/></w:trPr>' +
        header.map(function (text, i) {
          return cell(text, {
            bold: true, fill: self.accent, color: 'FFFFFF',
            widthCm: widths && widths[i],
          });
        }).join('') + '</w:tr>';
    }
    rows.forEach(function (row) {
      xml += '<w:tr>';
      for (var i = 0; i < nCols; i++) {
        xml += cell(row[i], {
          widthCm: widths && widths[i],
          align: opts.align && opts.align[i] ? opts.align[i] : null,
          bold: opts.boldRows && opts.boldRows(row),
        });
      }
      xml += '</w:tr>';
    });
    xml += '</w:tbl>';
    this.body.push(xml);
    this.spacer();
    return this.tableNo;
  };

  /* Two label/value pairs per row, like the field sheet headers. */
  ReportBuilder.prototype.keyValueTable = function (pairs, options) {
    var rows = [];
    for (var i = 0; i < pairs.length; i += 2) {
      var a = pairs[i], b = pairs[i + 1] || ['', ''];
      rows.push([a[0], a[1], b[0], b[1]]);
    }
    var before = this.tableNo;
    this.table(rows, Object.assign({
      colWidthsCm: [3.6, 4.4, 3.6, 4.4], fontSize: 9.5,
    }, options || {}));
    /* a header block is not a numbered table in the report's sequence */
    this.tableNo = before;
    return this;
  };

  /* --- figures -------------------------------------------------------------- */

  /* image: {dataUrl, mime} - PNG bytes are extracted and added as a media part. */
  ReportBuilder.prototype.figure = function (image, caption, widthCm) {
    if (!image || !image.dataUrl) return null;
    this.figureNo += 1;
    var index = this.images.length + 1;
    var mime = image.mime || 'image/png';
    var extension = /jpe?g/i.test(mime) ? 'jpeg' : 'png';
    this.images.push({
      name: 'image' + index + '.' + extension,
      bytes: S.base64ToBytes(image.dataUrl),
      mime: mime,
    });
    var rid = 'rIdImg' + index;
    var cm = widthCm || 15.0;
    var aspect = (image.height && image.width) ? image.height / image.width : 0.58;
    var cx = Math.round(cm * EMU_PER_CM);
    var cy = Math.round(cx * aspect);
    var drawing = '<w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">' +
      '<wp:extent cx="' + cx + '" cy="' + cy + '"/>' +
      '<wp:docPr id="' + index + '" name="Figure ' + this.figureNo + '" descr="' +
      esc(clean(caption)) + '"/>' +
      '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">' +
      '<pic:pic><pic:nvPicPr><pic:cNvPr id="' + index + '" name="' +
      esc('Figure ' + this.figureNo) + '"/><pic:cNvPicPr/></pic:nvPicPr>' +
      '<pic:blipFill><a:blip r:embed="' + rid + '"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>' +
      '<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="' + cx + '" cy="' + cy + '"/></a:xfrm>' +
      '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>' +
      '</a:graphicData></a:graphic></wp:inline></w:drawing>';
    this.paragraph('', { align: 'center', raw: '<w:r>' + drawing + '</w:r>' });
    this.paragraph('Figure ' + this.figureNo + '. ' + clean(caption),
      { bold: true, size: 9, align: 'center' });
    return this.figureNo;
  };

  ReportBuilder.prototype.references = function (entries) {
    var self = this;
    if (!entries || !entries.length) return this;
    this.heading('References', 1);
    entries.forEach(function (entry) {
      self.paragraph(entry, { indentCm: 0.8, hangingCm: 0.8, spaceAfter: 4 });
    });
    return this;
  };

  ReportBuilder.prototype.glossary = function (terms) {
    if (!terms || !terms.length) return this;
    this.heading('Glossary and Abbreviations', 1);
    this.table(terms, {
      header: ['Term', 'Meaning'], colWidthsCm: [3.5, 12.0], fontSize: 9.0,
    });
    return this;
  };

  /* The professional decision behind a figure, as recorded on the Depth Spine.
   *
   * The toolkit recommends; a named person accepts or overrides. An override
   * is the thing that ends up in front of the client under someone's name, so
   * it carries its reason and the figure it replaced - a report that printed
   * only the accepted number would hide the judgement that produced it. */
  ReportBuilder.prototype.signOff = function (records) {
    var self = this;
    var list = (records || []).filter(Boolean);
    if (!list.length) return this;
    this.heading('Professional Sign-off', 1);
    this.paragraph('Each figure below was reviewed against the toolkit\'s ' +
      'recommendation before this report was issued.');
    this.table(list.map(function (record) {
      return [
        record.label,
        record.status === 'accepted' ? 'Accepted' : 'Overridden',
        record.value,
        record.signatory + '\n' + record.at,
      ];
    }), {
      header: ['Stage', 'Decision', 'Certified value', 'Signed'],
      colWidthsCm: [3.6, 2.6, 4.4, 5.0], fontSize: 9.5,
      caption: 'Decisions recorded against this borehole.',
    });
    list.forEach(function (record) {
      if (record.status === 'overridden') {
        self.paragraph(record.label + ': the toolkit recommended ' +
          record.recommended + '. ' + (record.reason || 'No reason recorded.'));
      }
      if (!record.clean) {
        self.paragraph(record.label + ': signed with a data check still open. ' +
          'The flags on that stage are listed above.');
      }
    });
    return this;
  };

  ReportBuilder.prototype.signatures = function (roles) {
    var self = this;
    this.spacer();
    var rows = (roles || []).map(function (role) {
      return [role, '', ''];
    });
    this.table(rows, {
      header: ['Role', 'Name and signature', 'Date'],
      colWidthsCm: [4.5, 7.5, 3.5], fontSize: 9.5,
    });
    /* the signature block is not part of the numbered table sequence */
    self.tableNo -= 1;
    return this;
  };

  /* --- packaging ------------------------------------------------------------ */

  ReportBuilder.prototype.documentXml = function () {
    var sectPr = '<w:sectPr>' +
      '<w:footerReference w:type="default" r:id="rIdFooter"/>' +
      '<w:pgSz w:w="11906" w:h="16838"/>' +
      '<w:pgMar w:top="1418" w:right="1418" w:bottom="1418" w:left="1418" ' +
      'w:header="708" w:footer="708" w:gutter="0"/>' +
      '</w:sectPr>';
    return XML_HEAD + '<w:document ' + W_NS + '><w:body>' +
      this.body.join('') + sectPr + '</w:body></w:document>';
  };

  ReportBuilder.prototype.stylesXml = function () {
    var self = this;
    var half = Math.round(this.baseSize * 2);
    function heading(level, sizePt, spaceBefore) {
      return '<w:style w:type="paragraph" w:styleId="Heading' + level + '">' +
        '<w:name w:val="heading ' + level + '"/><w:basedOn w:val="Normal"/>' +
        '<w:next w:val="Normal"/><w:qFormat/>' +
        '<w:pPr><w:keepNext/><w:outlineLvl w:val="' + (level - 1) + '"/>' +
        '<w:spacing w:before="' + spaceBefore * 20 + '" w:after="120"/></w:pPr>' +
        '<w:rPr><w:rFonts w:ascii="' + esc(self.font) + '" w:hAnsi="' + esc(self.font) + '"/>' +
        '<w:b/><w:color w:val="' + self.accent + '"/>' +
        '<w:sz w:val="' + Math.round(sizePt * 2) + '"/></w:rPr></w:style>';
    }
    return XML_HEAD + '<w:styles ' + W_NS + '>' +
      '<w:docDefaults><w:rPrDefault><w:rPr>' +
      '<w:rFonts w:ascii="' + esc(this.font) + '" w:hAnsi="' + esc(this.font) +
      '" w:cs="' + esc(this.font) + '"/><w:sz w:val="' + half + '"/>' +
      '</w:rPr></w:rPrDefault>' +
      '<w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="276" w:lineRule="auto"/>' +
      '</w:pPr></w:pPrDefault></w:docDefaults>' +
      '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">' +
      '<w:name w:val="Normal"/><w:qFormat/></w:style>' +
      heading(1, 14, 12) + heading(2, 12, 8) + heading(3, 11, 8) +
      '<w:style w:type="paragraph" w:styleId="ListBullet">' +
      '<w:name w:val="List Bullet"/><w:basedOn w:val="Normal"/>' +
      '<w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>' +
      '<w:spacing w:after="60"/><w:ind w:left="720" w:hanging="360"/></w:pPr></w:style>' +
      '<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/>' +
      '<w:tblPr><w:tblCellMar><w:top w:w="60" w:type="dxa"/>' +
      '<w:left w:w="90" w:type="dxa"/><w:bottom w:w="60" w:type="dxa"/>' +
      '<w:right w:w="90" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style>' +
      '</w:styles>';
  };

  function numberingXml() {
    return XML_HEAD + '<w:numbering ' + W_NS + '>' +
      '<w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="hybridMultilevel"/>' +
      '<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/>' +
      '<w:lvlText w:val="•"/><w:lvlJc w:val="left"/>' +
      '<w:pPr><w:ind w:left="720" w:hanging="360"/></w:pPr>' +
      '<w:rPr><w:rFonts w:ascii="Symbol" w:hAnsi="Symbol" w:hint="default"/></w:rPr>' +
      '</w:lvl></w:abstractNum>' +
      '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>';
  }

  function footerXml() {
    return XML_HEAD + '<w:ftr ' + W_NS + '><w:p><w:pPr><w:jc w:val="center"/></w:pPr>' +
      '<w:r><w:rPr><w:sz w:val="18"/></w:rPr><w:fldChar w:fldCharType="begin"/></w:r>' +
      '<w:r><w:rPr><w:sz w:val="18"/></w:rPr>' +
      '<w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>' +
      '<w:r><w:rPr><w:sz w:val="18"/></w:rPr><w:fldChar w:fldCharType="separate"/></w:r>' +
      '<w:r><w:rPr><w:sz w:val="18"/></w:rPr><w:t>1</w:t></w:r>' +
      '<w:r><w:rPr><w:sz w:val="18"/></w:rPr><w:fldChar w:fldCharType="end"/></w:r>' +
      '</w:p></w:ftr>';
  }

  ReportBuilder.prototype.build = function () {
    var self = this;
    var imageTypes = {};
    this.images.forEach(function (img) {
      imageTypes[/jpe?g/i.test(img.mime) ? 'jpeg' : 'png'] = img.mime;
    });

    var contentTypes = XML_HEAD +
      '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
      '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
      '<Default Extension="xml" ContentType="application/xml"/>' +
      Object.keys(imageTypes).map(function (ext) {
        return '<Default Extension="' + ext + '" ContentType="' + imageTypes[ext] + '"/>';
      }).join('') +
      '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>' +
      '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>' +
      '<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>' +
      '<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>' +
      '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>' +
      '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>' +
      '</Types>';

    var rootRels = XML_HEAD +
      '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
      '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>' +
      '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>' +
      '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>' +
      '</Relationships>';

    var docRels = XML_HEAD +
      '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
      '<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>' +
      '<Relationship Id="rIdNumbering" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>' +
      '<Relationship Id="rIdFooter" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>' +
      this.images.map(function (img, i) {
        return '<Relationship Id="rIdImg' + (i + 1) + '" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/' +
          img.name + '"/>';
      }).join('') + '</Relationships>';

    var core = XML_HEAD +
      '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"' +
      ' xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/"' +
      ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">' +
      '<dc:title>' + esc(this.title) + '</dc:title>' +
      '<dc:creator>' + esc(this.style.organisation || 'Groundwater Toolkit') + '</dc:creator>' +
      '<cp:lastModifiedBy>' + esc(this.style.organisation || 'Groundwater Toolkit') + '</cp:lastModifiedBy>' +
      '</cp:coreProperties>';

    var app = XML_HEAD +
      '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"' +
      ' xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">' +
      '<Application>Groundwater Toolkit</Application></Properties>';

    var entries = [
      { name: '[Content_Types].xml', data: contentTypes, store: true },
      { name: '_rels/.rels', data: rootRels },
      { name: 'docProps/core.xml', data: core },
      { name: 'docProps/app.xml', data: app },
      { name: 'word/document.xml', data: this.documentXml() },
      { name: 'word/_rels/document.xml.rels', data: docRels },
      { name: 'word/styles.xml', data: this.stylesXml() },
      { name: 'word/numbering.xml', data: numberingXml() },
      { name: 'word/footer1.xml', data: footerXml() },
    ].concat(this.images.map(function (img) {
      return { name: 'word/media/' + img.name, data: img.bytes, store: true };
    }));

    return S.zip(entries);
  };

  ReportBuilder.prototype.save = async function (filename) {
    var bytes = await this.build();
    S.download(filename, new Blob([bytes], {
      type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    }));
    return bytes;
  };

  /* ============================================================== references */

  var REFERENCES = {
    rwsn_cost: 'Danert, K. (2015). Cost-Effective Boreholes: RWSN Borehole Costing ' +
      'Model and Guidance Notes. Rural Water Supply Network, St Gallen.',
    rwsn_pricing: 'Carter, R. C. (2014). Costing and Pricing: a Guide for Water Well ' +
      'Drilling Enterprises. RWSN/Skat, St Gallen.',
    rwsn_supervision: 'Adekile, D. (2014). Supervising Water Well Drilling: a Guide ' +
      'for Supervisors. RWSN/Skat, St Gallen.',
    rwsn_professional: 'Danert, K., Adekile, D. and Canuto, J. (2020). Professional ' +
      'Water Well Drilling: a UNICEF Guidance Note. UNICEF/Skat, New York.',
    unicef_toolkit: 'UNICEF (2016). Borehole Drilling: Planning, Contracting and ' +
      'Management. UNICEF WASH, New York.',
    who: 'World Health Organization (2022). Guidelines for Drinking-water Quality, ' +
      'fourth edition incorporating the first and second addenda. WHO, Geneva.',
    geology: 'Ministry of Water Resources and SALWACO (2017). Geology of Sierra ' +
      'Leone. Government of Sierra Leone, Freetown.',
    // the wording the CC BY-SA licence prescribes (THIRD_PARTY_NOTICES.md)
    bgs: 'British Geological Survey. 2019/2021. Africa Groundwater Atlas Country ' +
      'Hydrogeology Maps. Africa Groundwater Atlas ' +
      '(https://www2.bgs.ac.uk/africagroundwateratlas/index.cfm). Licensed CC BY-SA 4.0.',
    bgs_guide: 'Ó Dochartaigh, B. (2021). User Guide Version 1.2: Africa Groundwater ' +
      'Atlas Country Hydrogeology Maps. British Geological Survey Open Report OR/21/063.',
    stop_the_rot: 'RWSN (2021). Stop the Rot: Handpump Corrosion and Premature ' +
      'Failure in Sub-Saharan Africa. Rural Water Supply Network, St Gallen.',
    /* The browser printed 'the national acceptability limit' in three reports
     * and named no standard at all, while the Python reports cited this and
     * said in the citation what the limits are worth. */
    slsb: 'Sierra Leone Standards Bureau. Sierra Leone Standard for drinking ' +
      'water quality (SLS). Freetown: SLSB. Edition and date not verified ' +
      'against the issued specification: the national limits this toolkit ' +
      'applies are provisional (WHO or regional figures carried across) ' +
      'until confirmed against it.',
  };

  var GLOSSARY = [
    ['AB/2', 'Half the distance between the current electrodes in a Schlumberger sounding.'],
    ['Apparent resistivity', 'The resistivity a uniform earth would need to give the measured reading, in ohm-metres.'],
    ['Cooper-Jacob', 'A straight-line approximation to the Theis solution, valid at late pumping time.'],
    ['Drawdown', 'The fall of the water level below its static (pre-pumping) level.'],
    ['Overburden', 'The weathered and unconsolidated material above fresh bedrock.'],
    ['Safe yield', 'The rate the borehole can sustain over the design period after a safety factor.'],
    ['Saprolite', 'Chemically weathered rock that has kept its original structure.'],
    ['Specific capacity', 'Discharge divided by drawdown, in m³/h per metre.'],
    ['Static water level (SWL)', 'The rest water level in the borehole before pumping.'],
    ['Transmissivity (T)', 'The rate water moves through the full aquifer thickness, in m²/day.'],
    ['VES', 'Vertical Electrical Sounding, a one-dimensional resistivity depth probe.'],
  ];

  /* ============================================================ report bodies
   * The section structure mirrors groundwater/reporting/*.py so a report built
   * in the browser and one built by the Python package read the same way.
   */

  /* One grid ordinate as a coordinate, not as a quantity: "778000 m E (UTM
   * zone 28N)". Mirrors groundwater/utils.py utm_text. The reports printed
   * it through fmtNum, which gave "778,000" - a thousands separator and no
   * zone, which is a number nobody can type into a GPS, and which in a
   * country straddling zones 28N and 29N does not even say which grid it
   * belongs to. The zone rides on the easting only, and only where both
   * ordinates are present, because that is the pair that fixes a position. */
  function utmText(site, axis) {
    if (!site) return '';
    var value = site[axis];
    if (value === null || value === undefined || value === '') return '';
    var located = site.easting !== null && site.easting !== undefined &&
      site.northing !== null && site.northing !== undefined;
    var zone = (located && axis === 'easting')
      ? ' (UTM zone ' + (site.utm_zone ||
        C.inferZoneForSierraLeone(Number(site.easting))) + 'N)' : '';
    return C.pyFixed(Number(value), 0) + ' m ' +
      (axis === 'easting' ? 'E' : 'N') + zone;
  }

  function siteDetails(site, extra) {
    var pairs = [
      ['Client', site.client || '—'],
      ['Community', site.community || '—'],
      ['Chiefdom', site.chiefdom || '—'],
      ['District', site.district || '—'],
      ['Project', site.project || '—'],
      ['Project reference', site.project_ref || '—'],
    ];
    if (site.easting !== null && site.easting !== undefined) {
      pairs.push(['GPS easting', utmText(site, 'easting')]);
      pairs.push(['GPS northing', utmText(site, 'northing')]);
    }
    if (site.elevation_m !== null && site.elevation_m !== undefined) {
      pairs.push(['Elevation', C.fmtNum(site.elevation_m) + ' m']);
    }
    if (site.supervisor) pairs.push(['Field supervisor', site.supervisor]);
    if (site.contractor) pairs.push(['Contractor', site.contractor]);
    if (site.date) pairs.push(['Date', site.date]);
    return pairs.concat(extra || []);
  }

  /* Every report opens on where it is. The maps and the sentence above them
   * are built by the caller (the app knows the boundaries); this only places
   * them, so a report cannot end up with the maps and no explanation, or an
   * explanation and no maps. */
  function areaSection(b, context, heading) {
    var maps = context.areaMaps || [];
    if (!context.areaNote && !maps.length) return;
    if (heading) b.heading(heading, 2);
    if (context.areaNote) b.paragraph(context.areaNote, { align: 'justify' });
    maps.forEach(function (fig) {
      b.figure(fig.image, fig.caption, fig.widthCm || 14);
    });
  }

  /* The limit a parameter actually breached, matching its status. Taking the
   * WHO health value first regardless would print a limit the parameter did
   * not exceed beside a remark naming the one it did. Mirrors
   * groundwater.reporting.completion._breached_limit. */
  function breachedLimit(row) {
    if (row.status === 'exceeds_national') {
      return row.sl_standard || row.who_health || row.who_aesthetic || '';
    }
    if (row.status === 'exceeds_aesthetic') {
      return row.who_aesthetic || row.sl_standard || row.who_health || '';
    }
    return row.who_health || row.sl_standard || row.who_aesthetic || '';
  }

  /* arrays: for 'ves', the arrays the soundings were run with. The paragraph
   * said "a Schlumberger sounding ... its largest AB/2" over a Wenner survey,
   * whose spacing is a. */
  function limitationsParagraphs(kind, arrays) {
    var shared = 'The findings rest on the data recorded on the field sheets and ' +
      'on the standard interpretation methods named in this report. Field data ' +
      'carry measurement error, and the methods carry assumptions that are ' +
      'stated where they are used.';
    if (kind === 'ves') {
      var kinds = arrays && arrays.length ? arrays : ['schlumberger'];
      var reach = kinds.map(function (a) {
        return a === 'wenner'
          ? 'a Wenner sounding resolves the ground to roughly half of its largest ' +
            'electrode spacing a'
          : 'a Schlumberger sounding resolves the ground to roughly half of its ' +
            'largest AB/2';
      }).join(' and ');
      return [shared, 'Resistivity models are not unique: different layer ' +
        'combinations can fit the same sounding curve almost equally well ' +
        '(the equivalence and suppression problem), and ' + reach + ', not to the ' +
        'spacing itself: a layer that continues to that depth has no base in ' +
        'these data. A model whose misfit is above the target does not describe ' +
        'the curve closely, and the ranking discounts it for that. The ' +
        'interpretation is a guide to drilling, not a guarantee of water. Only ' +
        'drilling confirms the section.'];
    }
    if (kind === 'pumping') {
      return [shared, 'Storativity cannot be resolved from a single pumped ' +
        'well: it trades off against the effective well radius, so the value ' +
        'reported here is an assumption, not a measurement. The safe yield is ' +
        'therefore given as a range over the assumptions it rests on. Design ' +
        'to the lower figure where the supply must not fail in a dry year.'];
    }
    if (kind === 'quality') {
      return [shared, 'The assessment covers only the parameters analysed. A ' +
        'single sample describes the water at one moment; microbiological ' +
        'quality in particular varies with season and with the state of the ' +
        'headworks, so it should be re-tested after commissioning and ' +
        'periodically thereafter.'];
    }
    return [shared];
  }

  /* A reason raised as an exception message starts lower case and carries no
   * full stop; the report prints it as a sentence. Mirrors
   * reporting/geophysical.py _sentence. */
  function sentence(text) {
    var trimmed = String(text === null || text === undefined ? '' : text).trim();
    if (!trimmed) return trimmed;
    return trimmed.charAt(0).toUpperCase() + trimmed.slice(1) +
      (trimmed.charAt(trimmed.length - 1) === '.' ? '' : '.');
  }

  /* The maps and sections built from the survey's own soundings, and the list
   * of the ones it could not support. Mirrors
   * reporting/geophysical.py _add_subsurface_figures: the figures are the
   * caller's (the app draws them, inside the report build, on the print
   * palette), and this places them, heads them and writes down what was not
   * drawn and why. A report that quietly prints four figures where six were
   * planned tells a reviewer nothing about the two that are missing, and the
   * reason is usually a GPS position nobody recorded - which a reviewer can
   * ask for. */
  function subsurfaceSection(b, context) {
    var subsurface = context.subsurface || {};
    var figures = subsurface.figures || [];
    var notDrawn = subsurface.notDrawn || [];
    if (!figures.length && !notDrawn.length) return;
    b.heading('Subsurface maps from the survey', 2);
    if (figures.length) {
      b.paragraph('The maps in this section are drawn from the soundings ' +
        'themselves rather than from a national dataset, so they carry the ' +
        'survey\'s own resolution. Each interpolated surface is blanked ' +
        'outside the ground the soundings enclose: a contour beyond the last ' +
        'peg is the interpolator continuing a trend, and a borehole gets ' +
        'sited on it.', { align: 'justify' });
    }
    figures.forEach(function (fig) {
      b.figure(fig.image, fig.caption, fig.widthCm);
    });
    if (notDrawn.length) {
      b.paragraph(figures.length
        ? 'Not drawn from this survey, and why:'
        : 'No subsurface map or section could be drawn from this survey:',
      { bold: true });
      b.bullets(notDrawn.map(sentence));
    }
  }

  /* --- 1. geophysical survey ------------------------------------------------- */

  async function geophysicalReport(context) {
    var b = new ReportBuilder({ style: context.style, title: 'Geophysical Survey Report' });
    var site = context.site || {};
    var interpretations = context.interpretations || [];
    var figures = context.figures || [];

    b.cover(['Geophysical Survey Report',
      site.community ? site.community + (site.district ? ', ' + site.district : '') : ''],
      ['Vertical electrical sounding for borehole siting'],
      siteDetails(site));
    b.provisionalStamp(context.readiness);
    b.tableOfContents();

    var inversions = context.inversions || [];
    var vesCfg = context.ves || C.defaultConfig().ves;
    var analystOrder = !!(context.preferredOrder && context.preferredOrder.length);
    /* One ranking for the whole document, assigned before anything reads it,
     * on the settings the tables below are scored with, as
     * reporting/geophysical.py does; and one tie, by the test the tie
     * sentence and the "=1st" in the preference table use. The report used
     * to write "Drill at X (ranked 1st)" under a table that could not
     * separate X from the next point. An order the analyst set is a
     * judgment, not a score, and is not second-guessed. */
    if (interpretations.length) {
      C.rankInterpretations(interpretations, context.preferredOrder, vesCfg);
    }
    var suit = interpretations.length ? C.assessSiting(interpretations, vesCfg) : [];
    var ranked = interpretations.slice().sort(function (a, c) {
      return (a.rank || 99) - (c.rank || 99);
    });
    var best = ranked[0];
    var tied = (!analystOrder && suit.length >= 2 &&
      C.tiedLeaders(suit, vesCfg.ranking_tie_points)) ? ranked.slice(0, 2) : [];
    var at = tied.length ? ' at ' + best.sounding_id : '';
    b.executiveSummary([
      'A vertical electrical sounding survey was carried out at ' +
        (site.community || 'the site') + ' to select a drilling target. ' +
        interpretations.length + ' ' + S.plural(interpretations.length, 'sounding') +
        ' were made and interpreted as layered earth models.',
      best ? (tied.length
        ? 'Points ' + tied[0].sounding_id + ' and ' + tied[1].sounding_id +
          ' cannot be told apart on geophysical grounds, so either may be drilled, ' +
          'the choice between them to be made on access, sanitary distances and ' +
          'the community\'s preference. At ' + best.sounding_id + ' '
        : 'The recommended drilling point is ' + best.sounding_id + ', where ') +
        (best.water_zones.length
          ? 'possible water bearing zones are resolved from ' +
            best.water_zones.map(function (z) {
              return C.zoneText(z[0], z[1], C.zoneIsOpen(best, z)); }).join(', ')
          : 'no clear water bearing zone was resolved') +
        (best.basement_not_resolved
          ? '. The base of the deepest zone is not resolved: the sounding sees to ' +
            'about ' + C.fmtNum(best.investigation_depth_m) + ' m and the conductive ' +
            'ground continues below that, so the thickness is a minimum'
          : '') +
        '. A drilling depth of ' + C.drillingDepthText(best) + ' is recommended' +
        (tied.length
          ? ' there, and of ' + C.drillingDepthText(tied[1]) + ' at ' + tied[1].sounding_id
          : '') + '.' +
        (best.fit_quality === 'unreliable'
          ? ' The model at this point reproduces the readings to ' +
            C.pyFixed(best.fit_error_percent, 1) + ' percent (ERR), well above the ' +
            'target: the layer depths are indicative only.'
          : best.fit_quality === 'poor'
            ? ' The model at this point reproduces the readings to ' +
              C.pyFixed(best.fit_error_percent, 1) + ' percent (ERR), above the ' +
              'target, so the layer depths are approximate.'
            : '') : '',
    ], best ? [
      tied.length
        ? 'VES points the survey cannot separate: ' + tied[0].sounding_id + ' and ' +
          tied[1].sounding_id
        : 'Recommended VES point: ' + best.sounding_id,
      'Depth to bedrock' + at + ': ' + (best.depth_to_basement_m !== null
        ? C.fmtNum(best.depth_to_basement_m) + ' m' : 'not resolved'),
      'Interpreted aquifer thickness' + at + ': ' +
        (best.basement_not_resolved ? 'at least ' : '') +
        C.fmtNum(best.aquifer_thickness_m) + ' m',
      'Aquifer protective capacity' + at + ': ' + best.protective_capacity,
      'Recommended drilling depth: ' + (tied.length
        ? tied.map(function (i) {
            return C.drillingDepthText(i) + ' at ' + i.sounding_id; }).join('; ')
        : C.drillingDepthText(best)),
      'Ranking confidence' + at + ': ' +
        C.pyFixed(best.confidence === undefined ? 1 : best.confidence, 2),
    ] : []);

    b.heading('1. Introduction', 1);
    b.paragraph('This report presents the results of a geophysical survey ' +
      'carried out at ' + (site.community || 'the project site') +
      (site.chiefdom ? ', ' + site.chiefdom + ' chiefdom' : '') +
      (site.district ? ', ' + site.district + ' district' : '') +
      '. The purpose of the survey was to locate a drilling point with the best ' +
      'prospect of a productive borehole, and to recommend a drilling depth.',
      { align: 'justify' });

    areaSection(b, context, '1.1 Location and setting');

    b.heading('2. Background and Geology of the Project Area', 1);
    /* The paragraph is the engine's, _geology_for word for word: the page
     * that builds this report works it out from the site's position and
     * passes it in. A caller that does not gets the paragraph the Python
     * writes for a site with no position, rather than the fixed "crystalline
     * basement" text this used to print on the Bullom sands as well. */
    b.paragraph(context.geologyNote || C.geologyParagraph(site, null),
      { align: 'justify' });

    b.heading('3. Field Work', 1);
    b.heading('3.1 Reconnaissance Survey', 2);
    b.paragraph('The site was walked with the community to identify candidate ' +
      'points clear of latrines, graveyards, refuse pits and flood paths, and ' +
      'accessible to a drilling rig.', { align: 'justify' });
    /* The browser can never have an elevation model, and the Python report
     * always says so here. Silent, a reader took the survey point map for a
     * topographic one; and this is the sentence that explains why the ground
     * profile below is the only ground-level figure in the document. */
    b.paragraph('No elevation model was supplied with this survey, so no ' +
      'topographic map is drawn: the toolkit bundles none and invents none. ' +
      'The elevations the crew recorded at the soundings are the ground ' +
      'levels this report has.', { align: 'justify' });
    /* The ground surface along the traverse, in the position
     * reporting/geophysical.py gives it: at the end of the reconnaissance
     * section, where the reader has just been told where the points are and
     * before the survey itself is described. The caption is the engine's,
     * word for word with the Python's; the figure is absent, with no line
     * said about it, whenever the recorded levels will not support one, which
     * is how the Python omits it. */
    if (context.groundProfile) {
      b.figure(context.groundProfile.image, context.groundProfile.caption,
        context.groundProfile.widthCm);
    }
    b.heading('3.2 Geophysical Survey', 2);
    b.heading('3.2.1 Resistivity Profiling', 3);
    /* The array each sounding was run with, from its inversion (the two lists
     * are built in lockstep): the report said "a Schlumberger array" and "a
     * maximum AB/2 of 60 m" over a Wenner survey whose spacing a was 60 m and
     * whose AB/2 was 90 m. The reach of each array is worded as
     * reporting/geophysical.py _limitations words it. */
    var arrayOf = function (k) {
      var inv = inversions[k];
      return inv && String(inv.array_type || '').indexOf('wenner') === 0
        ? 'wenner' : 'schlumberger';
    };
    var reach = {};
    interpretations.forEach(function (interp, k) {
      if (!(interp.max_spacing_m && interp.investigation_depth_m)) return;
      var kind = arrayOf(k), was = reach[kind] || [0, 0];
      reach[kind] = [Math.max(was[0], interp.max_spacing_m),
        Math.max(was[1], interp.investigation_depth_m)];
    });
    var arrays = interpretations.map(function (interp, k) { return arrayOf(k); })
      .filter(function (a, k, all) { return all.indexOf(a) === k; }).sort();
    b.paragraph('Resistivity measurements were made with a ' +
      (arrays.length ? arrays : ['schlumberger']).map(function (a) {
        return a.charAt(0).toUpperCase() + a.slice(1);
      }).join(' and a ') + ' array. ' +
      'Apparent resistivity is computed from the measured resistance and the ' +
      'array geometric factor.', { align: 'justify' });
    b.heading('3.2.2 Selection of VES Points', 3);
    b.paragraph('Sounding points were placed on the candidate positions agreed ' +
      'with the community.', { align: 'justify' });
    b.heading('3.2.3 Vertical Electrical Sounding (VES)', 3);
    b.paragraph(Object.keys(reach).length
      ? Object.keys(reach).sort().map(function (kind) {
          return C.depthOfInvestigationText(kind, reach[kind][0], reach[kind][1], vesCfg);
        }).join(' ') + ' A layer that continues to that depth has no base in these data.'
      : 'The depth of investigation is a fraction of the largest electrode spacing, ' +
        'so any structure below it is not resolved.',
      { align: 'justify' });

    b.heading('4. Data Analysis and Interpretation', 1);
    b.paragraph('The sounding curves were inverted to layered earth models by ' +
      'damped least squares. The fit error quoted for each model is the root ' +
      'mean square relative difference between the measured and modelled ' +
      'apparent resistivities.', { align: 'justify' });

    for (var i = 0; i < interpretations.length; i++) {
      var interp = interpretations[i];
      b.heading(interp.sounding_id, 2);
      b.paragraph(interp.narrative, { align: 'justify' });
      b.table(interp.layers.map(function (layer) {
        return [
          String(layer.number),
          C.fmtNum(layer.rho, 4),
          layer.thickness_m !== null ? C.fmtNum(layer.thickness_m) : '—',
          C.fmtNum(layer.top_m),
          isFinite(layer.bottom_m) ? C.fmtNum(layer.bottom_m) : '—',
          layer.unit,
        ];
      }), {
        header: ['Layer', 'Resistivity (Ω·m)', 'Thickness (m)', 'Top (m)',
          'Bottom (m)', 'Interpretation'],
        caption: 'Layered model for ' + interp.sounding_id + '.',
        colWidthsCm: [1.4, 2.6, 2.2, 1.8, 1.8, 6.2],
      });
      /* the sentences reporting/geophysical.py _sounding_block writes under
       * the model table, worded once in the core: what else was tried, and
       * which boundary the curve does not settle */
      var inversion = inversions[i];
      if (inversion) {
        var tried = C.modelsTriedText(inversion, vesCfg);
        if (tried) b.paragraph(tried, { align: 'justify' });
        var weak = C.poorlyResolvedText(inversion.model);
        if (weak) b.paragraph(weak, { align: 'justify' });
      }
      var fig = figures.filter(function (f) { return f.soundingId === interp.sounding_id; });
      for (var k = 0; k < fig.length; k++) {
        b.figure(fig[k].image, fig[k].caption, fig[k].widthCm || 15);
      }
    }

    if (interpretations.length) {
      b.heading('Drill-target suitability', 2);
      b.table(C.drillingPreferenceTable(interpretations, context.preferredOrder, vesCfg)
        .map(function (row) {
          return [row['No.'], row['VES Point'], row.Layer, row['Thickness (m)'],
            row['Depth (m)'], row[C.LAYER_RESISTIVITY_COLUMN],
            row['Possible Water Zones (m)'], row['Max Drilling Depth (m)'], row.Ranking];
        }), {
        header: ['No.', 'VES Point', 'Layer', 'Thickness (m)', 'Depth (m)',
          'Layer resistivity (Ω·m)', 'Possible water zones (m)', 'Drilling depth', 'Ranking'],
        caption: 'Ranked drilling preference. The resistivities are those of the ' +
          'fitted layers, not the apparent resistivities read in the field; a water ' +
          'zone marked + continues below the depth the sounding resolves, so its ' +
          'base and the drilling depth are minima.' +
          (tied.length ? ' The two points marked =1st cannot be told apart on ' +
            'geophysical grounds.' : ''),
        fontSize: 8.5,
      });
      /* The scorecard reporting/geophysical.py _suitability_block prints under
       * the ranked table: the suitability, the confidence that discounts it
       * and the figure the points are ranked on, then the target or the tie,
       * worded once in the core. The browser report showed the ranking and
       * never the numbers it was decided on. */
      b.paragraph('Each surveyed point is given a transparent suitability score ' +
        'from 0 to 100. The score combines the interpreted water-bearing ' +
        'thickness, how well the resistivity of the water zone sits within the ' +
        'productive fractured or weathered window, the overburden profile, and ' +
        'the presence of a fractured zone at the basement contact. The scores ' +
        'rank the points as drilling targets.', { align: 'justify' });
      b.table(suit.map(function (s) {
        return [s.rank, s.sounding_id, C.pyFixed(s.suitability, 1),
          C.pyFixed(s.confidence, 2), C.pyFixed(s.suitability * s.confidence, 1),
          s.grade];
      }), {
        header: ['Rank', 'VES point', 'Suitability (0 to 100)', 'Confidence',
          'Weighted', 'Grade'],
        caption: 'Drill-target suitability of the surveyed points. Suitability is ' +
          'the geological score; confidence discounts it for a model fit above ' +
          'the target and for a water-bearing zone whose base the sounding never ' +
          'reached; the points are ranked on the weighted figure.',
        colWidthsCm: [1.4, 3.0, 3.6, 2.4, 2.2, 3.4],
      });
      b.paragraph(C.suitabilityVerdict(suit, vesCfg.ranking_tie_points) +
        (analystOrder ? ' The drilling preference above follows the order the ' +
          'analyst set, not these scores.' : ''), { align: 'justify' });
      /* The drill-target map, where reporting/geophysical.py _suitability_block
       * puts it: under the ranked table, above the subsurface maps. It is
       * written inside this heading rather than beside the call to
       * subsurfaceSection below so that the figure cannot come out from under
       * the heading that says what it ranks. Its caption changes with what
       * the figure shows - whether a star marks the recommended target, and
       * whether a surface is interpolated between the pegs - so it is taken
       * from the engine that drew it rather than written again here. A
       * survey with no scored point, or none carrying a position, sets
       * nothing here and the report says nothing: the Python writes no "not
       * drawn" line for this figure. */
      if (context.suitabilityMap) {
        b.figure(context.suitabilityMap.image, context.suitabilityMap.caption,
          context.suitabilityMap.widthCm);
      }
    }

    subsurfaceSection(b, context);

    b.heading('5. Conclusions and Recommendations', 1);
    if (best) {
      /* the points drilled for: the one ranked first, or both of a pair the
       * ranking cannot separate */
      var chosen = tied.length ? tied : [best];
      /* A depth is a minimum for one of two reasons, named as
       * reporting/geophysical.py _recommendations names them: the zone runs
       * on below the depth of investigation, or it ends inside it but the
       * margin drilled below it does not. */
      var openEnded = chosen.some(function (i) { return i.basement_not_resolved; });
      var capped = chosen.some(function (i) {
        return i.drilling_depth_capped && !i.basement_not_resolved;
      });
      var reason = openEnded && capped
        ? 'The water-bearing zone, or the margin drilled below it, runs past what ' +
          'the survey resolves'
        : openEnded ? 'The water-bearing zone continues below what the survey resolves'
          : capped ? 'The margin drilled below the deepest water zone runs past what ' +
            'the survey resolves' : '';
      var targets = function (interp) {
        return interp.water_zones.map(function (z) {
          return C.zoneCell(z[0], z[1], C.zoneIsOpen(interp, z)) + ' m'; }).join(', ');
      };
      b.bullets([
        tied.length
          ? 'Drill at ' + tied[0].sounding_id + ' or ' + tied[1].sounding_id +
            ', which the survey cannot separate on geophysical grounds; choose ' +
            'between them on access, sanitary distances and the community\'s ' +
            'preference.'
          : 'Drill at ' + best.sounding_id + ' (ranked ' + C.ordinal(best.rank || 1) + ').',
        'Recommended drilling depth: ' + (tied.length
          ? tied.map(function (i) {
              return C.drillingDepthText(i) + ' at ' + i.sounding_id; }).join('; ')
          : C.drillingDepthText(best)) + '.' +
          (reason
            ? ' ' + reason + ': drill on while the formation is water bearing, ' +
              'guided by the strikes and the penetration rate, and stop in fresh rock.'
            : ''),
        tied.length
          ? 'Target the interpreted water bearing zones: ' + tied.map(function (i) {
              return (targets(i) || 'none resolved') + ' at ' + i.sounding_id;
            }).join('; ') + '.'
          : best.water_zones.length
            ? 'Target the interpreted water bearing ' +
              S.plural(best.water_zones.length, 'zone') + ' at ' + targets(best) + '.'
            : 'No clear water bearing zone was resolved; treat the hole as exploratory.',
        'Case and screen against the zones confirmed by the drill cuttings, not ' +
          'against this model alone.',
      ]);
    }
    (context.recommendations || []).length && b.bullets(context.recommendations);

    b.heading('6. Limitations and Uncertainty', 1);
    limitationsParagraphs('ves', arrays).forEach(function (text) {
      b.paragraph(text, { align: 'justify' });
    });

    /* The checks the sheets raised, as reporting/geophysical.py
     * _verification_notes gathers them: every warning on a sounding the
     * report covers, once, with the sounding named where the flag does not
     * name it. Two overlap readings at AB/2 40 m a factor of 1.98 apart
     * reached no document. */
    var notes = (context.verificationNotes || []).slice();
    (context.soundings || []).forEach(function (sounding) {
      (sounding.flags || []).forEach(function (flag) {
        if (flag.level !== 'warning' && flag.level !== 'error') return;
        var text = flagText(flag.context ? flag
          : Object.assign({}, flag, { context: sounding.sounding_id }));
        if (notes.indexOf(text) < 0) notes.push(text);
      });
    });
    if (notes.length) {
      b.heading('Annex A. Data Verification Notes', 1);
      b.paragraph('The following checks were raised automatically during data ' +
        'processing and should be verified against the field notes.');
      b.bullets(notes);
    }

    b.references([REFERENCES.rwsn_professional, REFERENCES.geology, REFERENCES.bgs,
      REFERENCES.bgs_guide]);
    b.glossary(GLOSSARY);
    return b;
  }

  /* --- 2. borehole completion ------------------------------------------------ */

  /* Python's DataFlag.__str__: "[WARNING] code (context): message". */
  function flagText(flag) {
    return '[' + String(flag.level || '').toUpperCase() + '] ' + flag.code +
      (flag.context ? ' (' + flag.context + ')' : '') + ': ' + flag.message;
  }

  /* The design's own warnings, in the client document (completion._design_notes
   * and the same block in handover.py). A 19 mm annulus and a pump intake
   * inside a screen were flagged on the design object and reached no report;
   * the drawing went out clean. */
  function designNotes(b, design) {
    var notes = (design.flags || []).filter(function (f) {
      return f.level === 'warning' || f.level === 'error';
    }).map(flagText);
    if (notes.length) {
      b.paragraph('Design notes:', { bold: true });
      b.bullets(notes);
    }
  }

  /* The drawing of the design among the report's figures. The app tags it
   * with design: true; older callers are recognised by the caption they gave
   * it. The writer captions it itself, as Python does, so the words follow
   * design.as_built rather than whatever the page passed. */
  function designFigure(figures) {
    var tagged = figures.filter(function (f) { return f && f.design; });
    if (tagged.length) return tagged[0];
    var byCaption = figures.filter(function (f) {
      return f && /borehole (construction )?design|as-built borehole/i.test(f.caption || '');
    });
    return byCaption.length ? byCaption[0] : null;
  }

  /* The one intake depth the completion report prints (completion._pump_intake).
   * The design may have moved the yield recommendation's intake out of a
   * screen into plain casing; where a design exists its depth is the depth,
   * so the drawing, the tables and the summary agree. */
  function pumpIntake(context) {
    var design = context.design;
    if (design && design.pump_intake_m !== null && design.pump_intake_m !== undefined) {
      return design.pump_intake_m;
    }
    var yr = context.analysis ? context.analysis.yield_recommendation : null;
    return yr ? yr.pump_installation_depth_m : null;
  }

  async function completionReport(context) {
    var b = new ReportBuilder({ style: context.style, title: 'Borehole Completion Report' });
    var site = context.site || {}, log = context.log || {}, design = context.design;
    var figures = context.figures || [];
    var summaryRec = context.analysis ? context.analysis.yield_recommendation : null;

    b.cover(['Borehole Completion Report',
      (log.borehole_ref ? log.borehole_ref + ' — ' : '') + (site.community || '')],
      [], siteDetails(site, [
        ['Borehole reference', log.borehole_ref || ''],
        ['Total depth', log.total_depth_m ? C.fmtNum(log.total_depth_m) + ' m' : ''],
        ['Drilling method', log.drilling_method || ''],
        /* The driller's word for the hole, not this report's verdict on it.
         * A bare "Status: Successful" on a cover stamped PROVISIONAL reads
         * as the document contradicting itself (completion.py). */
        ['Status as recorded by the driller', log.status || ''],
      ]));
    b.provisionalStamp(context.readiness);
    b.tableOfContents();

    b.executiveSummary([
      'A borehole was drilled at ' + (site.community || 'the site') + ' to ' +
        (log.total_depth_m ? C.fmtNum(log.total_depth_m) + ' m' : 'the depth recorded below') +
        (log.water_strikes_m && log.water_strikes_m.length
          ? ', with water struck at ' + log.water_strikes_m.map(function (w) {
              return C.fmtNum(w) + ' m'; }).join(' and ')
          : '') + '.',
      /* "completed with" only when the screens are the ones the log records
       * as installed; otherwise this is the design. The annular fill is the
       * engine's label, so a 19 mm annulus is no longer "gravel packed". */
      design ? (design.as_built ? 'The borehole was completed with '
          : 'The construction design provides ') +
        C.fmtNum(design.total_screen_length_m) +
        ' m of screen in ' + design.screens.length + ' ' +
        S.plural(design.screens.length, 'section') + '; the annulus below the ' +
        'seal (' + C.formatG(design.gravel_pack[0]) + '-' +
        C.formatG(design.gravel_pack[1]) + ' m) carries ' + design.annular_fill_label +
        ', and the cement grout seal runs from surface to ' +
        C.formatG(design.sanitary_seal[1]) + ' m.' : '',
      /* the pumping report carries the "treat as indicative" basis and its
       * warnings; this one used to print the same yield without them, and
       * the handover certificate followed it */
      summaryRec && summaryRec.safe_yield_m3_per_h
        ? 'The recommended safe yield is ' + C.fmtNum(summaryRec.safe_yield_m3_per_h) +
          ' m3/h with the pump intake at ' + C.fmtNum(pumpIntake(context)) +
          ' m below the top of the casing.' +
          (summaryRec.is_indicative ? ' ' + summaryRec.confidence_text : '')
        : '',
    ], [
      log.status ? 'Outcome: ' + log.status : null,
      log.total_depth_m ? 'Total depth: ' + C.fmtNum(log.total_depth_m) + ' m' : null,
      design ? 'Screened ' + S.plural(design.screens.length, 'interval') + ': ' +
        design.screens.map(function (s) {
          // the construction table in this same report prints "25-35 m" from
          // the design's own summary rows; a key finding that said
          // "25.0-35.0 m" made one document give two readings of one screen
          return C.formatG(s.top_m) + '-' + C.formatG(s.bottom_m) + ' m'; }).join('; ') : null,
      summaryRec && summaryRec.safe_yield_m3_per_h
        ? 'Safe yield: ' + C.fmtNum(summaryRec.safe_yield_m3_per_h) + ' m3/h' +
          (summaryRec.is_indicative ? ' (indicative)' : '') + '.' : null,
    ]);

    b.heading('1. Introduction', 1);
    b.paragraph('This report records the drilling and construction of borehole ' +
      (log.borehole_ref || '') + ' at ' + (site.community || 'the project site') +
      '. It presents the drilling log, the construction details and the ' +
      (design && design.as_built ? 'as-built construction.' : 'construction design.'),
      { align: 'justify' });

    areaSection(b, context, '1.1 Location and setting');

    b.heading('2. Methodology', 1);
    b.paragraph('The borehole was drilled by ' + (log.drilling_method ||
      'rotary and down-the-hole hammer') + '. Cuttings were collected at each ' +
      'metre and logged by the supervising hydrogeologist; water strikes were ' +
      'recorded as they occurred.', { align: 'justify' });

    b.heading('3. Drilling', 1);
    var drillPairs = [
      ['Start date', log.start_date || '—'],
      ['Completion date', log.completion_date || '—'],
      ['Total depth', log.total_depth_m ? C.fmtNum(log.total_depth_m) + ' m' : '—'],
      ['Water strikes', (log.water_strikes_m || []).length
        ? log.water_strikes_m.map(function (w) { return C.fmtNum(w) + ' m'; }).join(', ') : 'none'],
      ['Grouting depth', log.grouting_depth_m ? C.fmtNum(log.grouting_depth_m) + ' m' : '—'],
      ['Status', log.status || '—'],
    ];
    b.keyValueTable(drillPairs);

    b.heading('4. Borehole Log Data', 1);
    b.table((log.intervals || []).map(function (interval) {
      return [
        C.fmtNum(interval.top_m) + '–' + C.fmtNum(interval.bottom_m),
        C.fmtNum(interval.bottom_m - interval.top_m),
        interval.description || '—',
        interval.bit_diameter_in ? C.fmtNum(interval.bit_diameter_in) + '"' : '—',
      ];
    }), {
      header: ['Depth (m)', 'Thickness (m)', 'Lithology', 'Bit'],
      caption: 'Drilling log.', colWidthsCm: [2.6, 2.4, 8.6, 2.0],
    });

    /* completion.py: the heading, the note, the summary table, the drawing,
     * the design basis and the design notes, in that order. */
    var designFig = design ? designFigure(figures) : null;
    if (design) {
      b.heading('5. Borehole Construction' + (design.as_built ? '' : ' Design'), 1);
      /* The drilling template records the grout depth and, when the crew
       * fills it in, the screens installed; without those the drawing is a
       * design the rules generated from the log, and it used to be
       * captioned "as-built" all the same. */
      b.paragraph(design.construction_note, { align: 'justify', italic: true });
      b.table(C.designSummaryRows(design), {
        header: ['Item', 'Detail'],
        caption: design.as_built ? 'As-built construction summary.'
          : 'Construction design summary.',
        colWidthsCm: [5.0, 10.6],
      });
      if (designFig) {
        b.figure(designFig.image, design.as_built
          ? 'As-built borehole record with lithology and construction columns.'
          : 'Borehole construction design generated from the drilling log, ' +
            'with lithology and construction columns.',
          designFig.widthCm || 13);
      }
      if (design.design_basis && design.design_basis.length) {
        b.paragraph('Design basis:', { bold: true });
        b.bullets(design.design_basis);
      }
      designNotes(b, design);
    }
    figures.forEach(function (f) {
      if (f !== designFig) b.figure(f.image, f.caption, f.widthCm || 13);
    });

    /* Sections 6 to 9, which the Python builder has always written and this
     * one stopped short of. A completion report that ends at the casing
     * schedule does not say what the borehole yields, how the pump sits in
     * it, whether the water is drinkable or what anyone should do next -
     * which is most of what the client reads it for. */
    var analysis = context.analysis || null;
    var assessment = context.assessment || null;
    var test = analysis ? analysis.test : null;
    var rec = analysis ? analysis.yield_recommendation : null;
    var section = design ? 6 : 5;

    if (analysis) {
      b.heading(section + '. Pumping Test', 1);
      var steps = (test && test.steps) || [];
      var last = steps.length ? steps[steps.length - 1] : null;
      /* the maximum drawdown is measured at the end of the last step, so the
       * rate quoted beside it has to be that step's, not step one's */
      var q = last ? last.discharge_m3_per_h : null;
      var rows = [
        ['Test type', test ? C.testTypeText(test.test_type) : '—'],
        ['Duration', test && test.pumping_duration_min
          ? C.fmtNum(test.pumping_duration_min) + ' min' : '—'],
        [steps.length > 1 ? 'Discharge (final step)' : 'Discharge',
          q ? C.fmtNum(q) + ' m3/h' : 'pending'],
        ['Static water level', test && test.static_water_level_m !== null &&
          test.static_water_level_m !== undefined
          ? C.fmtNum(test.static_water_level_m) + ' m' : '—'],
        ['Pump setting during the test', test && test.pump_setting_m
          ? C.fmtNum(test.pump_setting_m) + ' m' : 'not recorded'],
        ['Maximum drawdown', analysis.max_drawdown_m
          ? C.fmtNum(analysis.max_drawdown_m) + ' m' : '—'],
      ];
      if (analysis.transmissivity_m2_per_day) {
        rows.push(['Transmissivity',
          C.fmtNum(analysis.transmissivity_m2_per_day) + ' m2/day' +
          (analysis.transmissivity_source
            ? ' (' + C.METHOD_LABELS[analysis.transmissivity_source] + ')' : '')]);
      }
      if (rec && rec.specific_capacity_m3hr_per_m) {
        /* a rate over a drawdown at a time, not a property of the borehole */
        rows.push(['Specific capacity',
          C.formatG(C.roundSig(rec.specific_capacity_m3hr_per_m, 2), 2) +
          ' m3/h per m (' + rec.specific_capacity_basis + ')']);
      }
      if (rec && rec.safe_yield_m3_per_h) {
        rows.push(['Safe yield', C.yieldRangeText(rec)]);
        rows.push(['Yield confidence', rec.is_indicative
          ? 'indicative: ' + rec.confidence_reasons.join('; ') : 'established']);
      }
      b.table(rows, { header: ['Item', 'Value'], caption: 'Pumping test summary.',
        colWidthsCm: [5.6, 10.0] });
      section += 1;
    }

    b.heading(section + '. Borehole Characteristics and Installation', 1);
    var swl = test && test.static_water_level_m !== null &&
      test.static_water_level_m !== undefined ? test.static_water_level_m : null;
    var lastStep = test && test.steps && test.steps.length
      ? test.steps[test.steps.length - 1] : null;
    var dwl = lastStep && lastStep.water_level_m && lastStep.water_level_m.length
      ? Number(lastStep.water_level_m[lastStep.water_level_m.length - 1]) : null;
    var flow = lastStep ? lastStep.discharge_m3_per_h : null;
    b.keyValueTable([
      ['Borehole depth', log.total_depth_m ? C.fmtNum(log.total_depth_m) + ' m' : '—'],
      ['Borehole diameter', design ? C.formatG(design.borehole_diameter_in) + '"' : '—'],
      ['Static water level', swl !== null ? C.fmtNum(swl) + ' m' : '—'],
      ['Dynamic water level at the end of the test',
        dwl !== null ? C.fmtNum(dwl) + ' m' : '—'],
      ['Drawdown', (dwl !== null && swl !== null)
        ? C.fmtNum(dwl - swl) + ' m' : '—'],
      /* the same unit as every other rate on the page; 2,930 L/h beside
       * 0.97 m3/h read as two different boreholes */
      ['Test discharge', flow ? C.fmtNum(flow) + ' m3/h' : 'pending'],
      /* Blank, not 'Handpump'. Nothing in this app records which pump was
       * installed, so the fallback asserted one on every borehole it wrote a
       * completion report for - a claim about equipment nobody had entered.
       * Python prints inputs.pump_type and leaves it empty. */
      ['Pump type', context.pumpType || ''],
      ['Pump setting during the test', test && test.pump_setting_m
        ? C.fmtNum(test.pump_setting_m) + ' m' : 'not recorded'],
      ['Recommended pump intake', pumpIntake(context)
        ? C.fmtNum(pumpIntake(context)) + ' m below the top of the casing'
        : 'pending'],
    ]);
    section += 1;

    if (assessment) {
      b.heading(section + '. Water Quality Summary', 1);
      b.paragraph(assessment.verdict, { align: 'justify' });
      var exceed = assessment.all_exceedances || [];
      if (exceed.length) {
        b.table(exceed.map(function (r) {
          return [r.parameter, C.fmtNum(r.value), r.unit || '',
            breachedLimit(r), r.remark || ''];
        }), {
          header: ['Parameter', 'Value', 'Unit', 'Limit', 'Remark'],
          caption: 'Parameters above guideline or standard limits.',
          fontSize: 9, colWidthsCm: [3.8, 1.8, 1.8, 2.2, 6.0],
        });
        /* A national limit the quality report calls provisional is
         * provisional here too. This table states the limit a parameter
         * breached without the column the quality report carries, so a
         * reader met the words "national standard" with nothing to say the
         * edition behind them is unverified (completion.py). */
        if (C.provisionalNationalParameters().length) {
          b.paragraph(C.PROVISIONAL_NATIONAL_NOTE, { align: 'justify', italic: true });
        }
      }
      section += 1;
    }

    b.heading(section + '. Recommendations and Conclusions', 1);
    var advice = [];
    var successful = String(log.status || '').toLowerCase().indexOf('success') === 0;
    /* "Successful and sustainable" is two claims. The log supports the
     * first; only an established yield supports the second, and a
     * 30-minute test inside its casing storage used to be certified as both. */
    if (rec && rec.safe_yield_m3_per_h && !rec.is_indicative) {
      advice.push('The borehole is successful and sustainable when operated ' +
        'as recommended.');
    } else if (rec && rec.safe_yield_m3_per_h) {
      advice.push((successful ? 'The borehole is recorded as successful. ' : '') +
        'Whether it is sustainable at the recommended rate is indicative, not ' +
        'established: ' + rec.confidence_reasons.join('; ') + '. Confirm it by ' +
        'a longer test or by monitoring the pumping level in service.');
    } else if (successful) {
      advice.push('The borehole is recorded as successful; no sustainable yield ' +
        'has been established from the pumping test.');
    }
    if (rec && rec.safe_yield_m3_per_h) {
      advice.push('The recommended abstraction rate is ' +
        C.fmtNum(rec.safe_yield_m3_per_h) + ' m3/h (safety factor ' +
        C.formatG(rec.safety_factor) + ' applied to the long term yield' +
        (rec.is_indicative ? ', indicative' : '') + ').');
      if (pumpIntake(context)) {
        advice.push('The pump intake is set at ' +
          C.fmtNum(pumpIntake(context)) + ' m below the top of the casing' +
          (design ? ', in plain casing clear of the screens' : '') + '.');
      }
      advice.push('The pump should rest for at least one hour in every ' +
        'pumping cycle and the pumping water level should be checked routinely.');
    } else if (analysis && test && !C.hasDischarge(test)) {
      /* asked of the steps, as Python's PumpingTest.has_discharge is: the
       * browser's test carries no such field, so this said the discharge
       * must be supplied beside a sheet that recorded it */
      advice.push('The pumping test discharge must be supplied so the yield ' +
        'recommendation can be completed; abstraction figures remain pending.');
    }
    var state = assessment ? assessment.verdict_state : null;
    if (state === 'health_fail' || state === 'national_fail') {
      advice.push('Water treatment is required before drinking; see the water ' +
        'quality assessment.');
    } else if (state === 'indeterminate') {
      advice.push('The water quality results do not yet establish that the ' +
        'supply is safe to drink: ' +
        (assessment.uncertainties || []).join('; ') +
        '. Resolve these before the borehole is handed over.');
    } else {
      advice.push('Physico-chemical and bacteriological testing should be ' +
        'repeated at least once a year.');
    }
    b.bullets(advice);

    b.signOff(context.signOff);
    b.references([REFERENCES.rwsn_professional, REFERENCES.rwsn_supervision,
      REFERENCES.who, REFERENCES.slsb]);
    b.glossary(GLOSSARY);
    return b;
  }

  /* --- 3. pumping test ------------------------------------------------------- */

  /* Where the levels are measured from. The sheets record depth to water
   * from the top of the casing and never the casing's stick-up above ground,
   * so "below ground level" was a claim the data did not support. */
  var DATUM_TEXT = 'below the top of the casing, the datum the levels were measured from';

  /* reporting/pumping._levels_in_doubt: the analysis or the sheet says the
   * recorded levels cannot all be right. A report used to certify the curves
   * over levels 18 m below the pump intake. */
  function pumpLevelsInDoubt(analysis) {
    var flags = (analysis.flags || []).concat((analysis.test && analysis.test.flags) || []);
    return flags.some(function (f) { return C.LEVEL_FLAGS.indexOf(f.code) >= 0; });
  }

  async function pumpingReport(context) {
    var b = new ReportBuilder({ style: context.style, title: 'Pumping Test Report' });
    var analysis = context.analysis, test = analysis.test, site = test.site || {};
    var rec = analysis.yield_recommendation;
    var figures = context.figures || [];
    var levelsInDoubt = pumpLevelsInDoubt(analysis);

    /* the test type in words, never the parser's "step+recovery" token */
    b.cover(['Pumping Test Report',
      (test.borehole_ref ? test.borehole_ref + ' — ' : '') + (site.community || '')],
      [], siteDetails(site, [
        ['Borehole reference', test.borehole_ref || '—'],
        ['Test type', C.testTypeText(test.test_type)],
        ['Static water level', test.static_water_level_m !== null
          ? test.static_water_level_m.toFixed(2) + ' m' : '—'],
        ['Borehole depth', test.borehole_depth_m ? C.fmtNum(test.borehole_depth_m) + ' m' : '—'],
      ]));
    b.provisionalStamp(context.readiness);
    b.tableOfContents();

    /* The one pump intake depth this report prints, and why: the deeper of
     * the day-of-test recommendation and the seasonal projection's. */
    var seasonal = context.seasonal;
    var intake = C.pumpIntakeDepth(analysis, seasonal);
    var pumpDepth = intake[0], pumpDepthWhy = intake[1];
    var adoptedInfo = C.adoptedFit(analysis);
    var typeText = C.testTypeText(test.test_type);

    b.executiveSummary([
      'A ' + typeText + ' was carried out on borehole ' +
        (test.borehole_ref || '') + ' at ' + (site.community || 'the site') + '.',
      analysis.transmissivity_m2_per_day
        ? 'The transmissivity of the aquifer is about ' +
          S.sig(analysis.transmissivity_m2_per_day, 3) + ' m²/day' +
          (analysis.transmissivity_source
            ? ' (' + C.METHOD_LABELS[analysis.transmissivity_source] + ')' : '') +
          '. The recommended safe yield is ' + C.yieldRangeText(rec) +
          (rec.is_indicative ? ' (indicative)' : '') + ', with the pump intake set at ' +
          (pumpDepth !== null
            ? C.fmtNum(pumpDepth) + ' m ' + DATUM_TEXT +
              (pumpDepthWhy ? ', ' + pumpDepthWhy : '')
            : 'a depth to be confirmed') + '.' +
          (rec.is_indicative ? ' ' + rec.confidence_text : '')
        /* reporting/pumping._executive_summary: levels the sheet shows cannot
         * be right are never presented as curves to read a result from */
        : (levelsInDoubt
          ? 'The recorded water levels are inconsistent with the stated static ' +
            'level, pump setting or borehole depth (see the data verification ' +
            'notes), so the curves are shown as recorded and their drawdowns are ' +
            'not to be relied on; the'
          : 'The drawdown and recovery curves are plotted from the readings as ' +
            'recorded, but the') +
          ' transmissivity and safe yield are pending because ' +
          (rec.pending_reason || 'the analysis is incomplete') + '.',
    ], [
      analysis.transmissivity_m2_per_day
        ? 'Transmissivity: ' + S.sig(analysis.transmissivity_m2_per_day, 3) + ' m²/day' +
          (analysis.transmissivity_source
            ? ' (' + C.METHOD_LABELS[analysis.transmissivity_source] + ')' : '') : null,
      rec.specific_capacity_m3hr_per_m
        ? 'Specific capacity: ' + C.formatG(C.roundSig(rec.specific_capacity_m3hr_per_m, 2), 2) +
          ' m³/h per m (' + rec.specific_capacity_basis + ')' : null,
      rec.safe_yield_m3_per_h ? 'Safe yield: ' + C.yieldRangeText(rec) +
        (rec.is_indicative ? ' (indicative)' : '') : null,
      pumpDepth !== null ? 'Pump installation depth: ' + C.fmtNum(pumpDepth) + ' m' : null,
      rec.safe_yield_m3_per_h
        ? (rec.is_indicative
          ? 'Confidence: indicative - ' + rec.confidence_reasons[0] + '.'
          : 'Confidence: established.') : null,
    ]);

    b.heading('1. Test Details', 1);
    b.keyValueTable([
      ['Borehole', test.borehole_ref || '—'],
      ['Test type', typeText],
      ['Static water level', test.static_water_level_m !== null
        ? test.static_water_level_m.toFixed(2) + ' m' : '—'],
      ['Pump setting during test', test.pump_setting_m
        ? C.fmtNum(test.pump_setting_m) + ' m' : 'not recorded'],
      ['Pumping duration', test.pumping_duration_min
        ? C.fmtNum(test.pumping_duration_min) + ' min' : '—'],
      ['Step length', test.step_length_min ? C.fmtNum(test.step_length_min) + ' min' : '—'],
    ]);
    b.paragraph('Water levels are depths below the top of the casing, the datum ' +
      'the field sheet records them from; the casing\'s stick-up above ground is ' +
      'not recorded, so every depth in this report is to that datum.',
      { italic: true });

    areaSection(b, context, '1.1 Location and setting');

    b.heading('2. Field Data', 1);
    b.paragraph('Water levels were measured with a dip meter against a fixed ' +
      'datum. Drawdown is computed as the water level minus the static water ' +
      'level; the incremental drawdown column on the field sheet is not used.',
      { align: 'justify' });
    (test.steps || []).forEach(function (step) {
      b.table(step.time_min.map(function (t, i) {
        return [C.fmtNum(t), step.water_level_m[i].toFixed(2),
          test.static_water_level_m !== null
            ? (step.water_level_m[i] - test.static_water_level_m).toFixed(2) : '—'];
      }), {
        header: ['Time (min)', 'Water level (m)', 'Drawdown (m)'],
        caption: step.label + (step.discharge_m3_per_h
          ? ' at ' + S.sig(step.discharge_m3_per_h, 3) + ' m³/h'
          : ' (discharge not recorded)'),
        colWidthsCm: [3.4, 4.0, 4.0], fontSize: 9,
      });
    });

    /* One bold sentence under a method's paragraph when its T is passed over. */
    function notAdopted(method) {
      var why = C.whyNotAdopted(analysis, method);
      if (!why) return;
      if (analysis.transmissivity_source === method && !adoptedInfo.qualifies) {
        b.paragraph('Adopted as the best available, not because it meets the ' +
          'standard: ' + why + '.', { bold: true });
      } else {
        b.paragraph('Not adopted for the yield: ' + why + '.', { bold: true });
      }
    }

    if (analysis.max_drawdown_m !== null && analysis.max_drawdown_m !== undefined) {
      b.paragraph('The maximum drawdown reached ' + C.fmtNum(analysis.max_drawdown_m) +
        ' m below the static water level' +
        (levelsInDoubt ? ', as recorded; the notes below say why the recorded ' +
          'levels cannot all be right' : '') + '.');
    }
    if (analysis.casing_storage_min) {
      /* worded from the adoption: "no straight line is read from it" stood a
       * page above a Cooper-Jacob line read inside the period and adopted as
       * the best available */
      var casingSource = analysis.transmissivity_source;
      var adoptedInside = casingSource && Object.prototype.hasOwnProperty.call(
        analysis.disqualified || {}, casingSource);
      b.paragraph('Casing storage: with a ' +
        C.formatG((context.config && context.config.pumping
          ? context.config.pumping : C.defaultConfig().pumping).casing_diameter_in) +
        ' inch casing and the specific capacity at the end of the first step, the ' +
        'water standing in the casing supplies the pump for about the first ' +
        C.pyFixed(analysis.casing_storage_min, 0) + " minutes (Schafer's rule). " +
        'Drawdown inside that period is the borehole emptying, not the aquifer ' +
        'responding' +
        (adoptedInside
          ? '. No fit outside it can be adopted, so the ' +
            C.METHOD_LABELS[casingSource] + ' value read inside it is used only ' +
            'as the best available.'
          : ', and no straight line is read from it.'), { align: 'justify' });
    }
    /* The analysis's own notes, as the Python report prints them: the
     * browser report carried none, so a sheet whose levels ran below the pump
     * reached the client with nothing to say so. */
    if ((analysis.flags || []).length) {
      b.paragraph('Data verification notes:', { bold: true });
      b.bullets(analysis.flags.map(flagText));
    }

    b.heading('3. Analysis', 1);
    if (analysis.cooper_jacob) {
      b.heading('Cooper-Jacob straight line', 2);
      b.paragraph('The straight line fitted to drawdown against the logarithm ' +
        'of time over ' + analysis.cooper_jacob.fit_window_min[0].toFixed(0) + ' to ' +
        analysis.cooper_jacob.fit_window_min[1].toFixed(0) + ' minutes has a slope ' +
        'of ' + analysis.cooper_jacob.slope_m_per_log_cycle.toFixed(3) + ' m per log ' +
        'cycle, giving a transmissivity of ' +
        S.sig(analysis.cooper_jacob.transmissivity_m2_per_day, 3) + ' m²/day. ' +
        analysis.cooper_jacob.u_check + '.', { align: 'justify' });
      notAdopted('cooper_jacob');
    }
    if (analysis.recovery) {
      var recFit = analysis.recovery;
      b.heading('Theis recovery', 2);
      var timeText = recFit.equivalent_time
        ? 'an equivalent pumping time of ' + C.pyFixed(recFit.pumping_time_min, 0) +
          ' minutes at the last rate of ' + C.fmtNum(recFit.discharge_m3_per_h) +
          ' m³/h (the volume pumped over all the steps, at that rate)'
        : 'the ' + C.formatG(recFit.pumping_time_min) + ' minutes pumped';
      b.paragraph('With t/t\' formed from ' + timeText + ', the recovery slope is ' +
        C.fmtNum(recFit.slope_m_per_log_cycle) + ' m per log cycle (r² = ' +
        recFit.r_squared.toFixed(3) + '), giving a transmissivity of ' +
        S.sig(recFit.transmissivity_m2_per_day, 3) + ' m²/day. The fitted line ' +
        'meets t/t\' = 1 at ' + C.fmtNum(recFit.intercept_m) + ' m of residual ' +
        'drawdown, where the method requires zero. Residual drawdown at the end ' +
        'of monitoring was ' + C.fmtNum(recFit.residual_at_end_m) + ' m.' +
        (C.whyNotAdopted(analysis, 'recovery') ? ''
          : ' Recovery derived transmissivity is generally the most reliable ' +
            'single well estimate because it is unaffected by pumping rate ' +
            'fluctuations and well losses.'),
        { align: 'justify' });
      notAdopted('recovery');
    }
    if (analysis.theis) {
      b.heading('Theis type curve', 2);
      b.paragraph('A least squares fit of the Theis well function gives a ' +
        'transmissivity of ' + S.sig(analysis.theis.transmissivity_m2_per_day, 3) +
        ' m²/day with a storativity of ' + S.sig(analysis.theis.storativity, 2) +
        (analysis.theis.storativity_reliable ? '.'
          : '. Storativity is not resolvable from a single pumped well and is ' +
            'reported for completeness only.'), { align: 'justify' });
      notAdopted('theis');
    }
    if (analysis.step_test) {
      var st = analysis.step_test;
      b.heading('Step drawdown analysis', 2);
      b.paragraph('The Hantush-Bierschenk analysis separates aquifer loss from ' +
        'well loss: B = ' + S.sig(st.aquifer_loss_B, 3) +
        ' day/m² and C = ' + S.sig(st.well_loss_C, 3) + ' day²/m⁵' +
        (st.two_point
          ? ', fitted through ' + st.steps.length + ' points. ' + C.TWO_POINT_NOTE + '.'
          : ', fitted with r² = ' + st.r_squared.toFixed(3) + '.') +
        (st.fit_note ? ' Note: ' + st.fit_note + '.' : ''),
        { align: 'justify' });
      b.table(st.steps.map(function (s) {
        return [String(s.step), S.sig(s.discharge_m3_per_h, 3),
          s.drawdown_end_m.toFixed(2), S.sig(s.sw_over_q_day_per_m2, 3),
          st.fit_note ? 'n/a' : s.efficiency_percent.toFixed(0) + '%' +
            (st.two_point ? ' (indicative)' : '')];
      }), {
        header: ['Step', 'Q (m³/h)', 'Drawdown (m)', 's/Q (day/m²)', 'Well efficiency'],
        caption: 'Step test results.',
      });
    }
    figures.forEach(function (f) { b.figure(f.image, f.caption, f.widthCm || 15); });

    b.heading('4. Results Summary', 1);
    /* every method that fitted, what it gave and what it is worth */
    var methodRows = [];
    ['cooper_jacob', 'theis', 'recovery'].forEach(function (key) {
      var result = analysis[key];
      if (!result) return;
      var status;
      if (key === analysis.transmissivity_source) {
        status = adoptedInfo.qualifies ? 'adopted'
          : 'adopted as the best available; ' + C.whyNotAdopted(analysis, key);
      } else {
        status = C.whyNotAdopted(analysis, key) || 'not adopted';
      }
      methodRows.push([C.METHOD_LABELS[key],
        S.sig(result.transmissivity_m2_per_day, 3),
        status.charAt(0).toUpperCase() + status.slice(1)]);
    });
    if (methodRows.length) {
      b.table(methodRows, {
        header: ['Method', 'Transmissivity (m²/day)', 'Status'],
        caption: 'Transmissivity estimates and what each is worth.',
        colWidthsCm: [3.6, 3.4, 8.6],
      });
    } else {
      b.paragraph('Transmissivity: pending (discharge not recorded).', { bold: true });
    }
    b.table([
      ['Transmissivity adopted for the yield', analysis.transmissivity_m2_per_day
        ? S.sig(analysis.transmissivity_m2_per_day, 3) + ' m²/day (' +
          C.METHOD_LABELS[analysis.transmissivity_source] + ')' : 'pending'],
      ['Maximum drawdown', analysis.max_drawdown_m !== null
        ? analysis.max_drawdown_m.toFixed(2) + ' m' +
          (levelsInDoubt ? ', as recorded; see the data verification notes' : '')
        : '—'],
      ['Specific capacity', rec.specific_capacity_m3hr_per_m
        ? C.formatG(C.roundSig(rec.specific_capacity_m3hr_per_m, 2), 2) +
          ' m³/h per m (' + rec.specific_capacity_basis + ')' : 'pending'],
      ['Confidence', rec.safe_yield_m3_per_h
        ? (rec.is_indicative ? 'indicative' : 'established') : 'pending'],
      ['Recommended pump installation depth', pumpDepth !== null
        ? C.fmtNum(pumpDepth) + ' m' + (pumpDepthWhy ? ', ' + pumpDepthWhy : '')
        : 'pending'],
      ['Pump setting during the test', test.pump_setting_m
        ? C.fmtNum(test.pump_setting_m) + ' m' : 'not recorded'],
    ], { header: ['Quantity', 'Value'], caption: 'Yield summary.',
      colWidthsCm: [7.0, 8.6] });

    b.heading('5. Yield Recommendation', 1);
    b.paragraph(rec.basis, { align: 'justify' });
    if (rec.safe_yield_m3_per_h) {
      b.table([
        ['Available drawdown', rec.available_drawdown_m !== null
          ? rec.available_drawdown_m.toFixed(2) + ' m' : '—'],
        ['Usable drawdown', rec.usable_drawdown_m !== null
          ? rec.usable_drawdown_m.toFixed(2) + ' m' : '—'],
        ['Long term yield', rec.long_term_yield_m3_per_h.toFixed(2) + ' m³/h'],
        ['Safe yield (with safety factor ' + rec.safety_factor + ')',
          C.yieldRangeText(rec) ],
        ['Confidence', rec.is_indicative ? 'indicative' : 'established'],
        ['Recommended pump intake', pumpDepth !== null
          ? C.fmtNum(pumpDepth) + ' m ' + DATUM_TEXT : '—'],
      ], { header: ['Quantity', 'Value'], caption: 'Yield recommendation.',
        colWidthsCm: [7.0, 8.6] });
      if (rec.envelope_basis) b.paragraph(rec.envelope_basis, { align: 'justify' });
      if (rec.pump_depth_basis) b.paragraph(rec.pump_depth_basis, { align: 'justify' });
      b.paragraph(rec.confidence_text, { align: 'justify', bold: rec.is_indicative });
      b.bullets([
        'Operate the borehole at no more than ' + C.fmtNum(rec.safe_yield_m3_per_h) +
          ' m³/h' + (rec.is_indicative ? ' (indicative; see above)' : '') + '.',
        'Install the pump intake at ' + C.fmtNum(pumpDepth) + ' m ' + DATUM_TEXT +
          (pumpDepthWhy ? ', ' + pumpDepthWhy : '') +
          ', in plain casing: where that depth falls within a screen, ' +
          'the borehole design sets it just below that screen.',
        'Monitor the pumping water level and re-assess the yield if the level ' +
          'approaches the pump intake.',
      ]);
    } else {
      b.paragraph('The yield recommendation is pending: ' +
        (rec.pending_reason || 'required inputs are missing') + '.', { bold: true });
    }

    if (seasonal && seasonal.is_established) {
      b.heading('5.1 Through the year', 2);
      b.paragraph('A pumping test measures one day. The borehole has to ' +
        'supply the village on the worst day, and those are months apart: the ' +
        'water table is recharged through the single wet season, peaks at the ' +
        'end of it and falls through the dry season to an annual low in April ' +
        'or May. The same test therefore means different things depending on ' +
        'when it was run, so the yield is reported here at each of three ' +
        'water levels rather than at one.', { align: 'justify' });
      if (seasonal.month) {
        b.paragraph('This test was run in ' + C.MONTH_NAMES[seasonal.month - 1] +
          ', the ' + seasonal.season + '.');
      } else if (seasonal.month_note) {
        b.paragraph(seasonal.month_note + ' The whole annual range is ' +
          'therefore reserved, which is the conservative reading.',
        { bold: true });
      }
      b.table(seasonal.scenarios.map(function (sc) {
        return [sc.title, C.pyFixed(sc.decline_m, 1),
          C.fmtNum(sc.static_water_level_m), C.fmtNum(sc.available_drawdown_m),
          C.fmtNum(sc.safe_yield_m3_per_h),
          C.fmtNum(sc.pump_installation_depth_m)];
      }), {
        header: ['Scenario', 'Further decline (m)', 'Static level (m)',
          'Available drawdown (m)', 'Safe yield (m³/h)', 'Pump intake (m)'],
        caption: 'Safe yield and pump setting at each seasonal water level.',
      });
      b.paragraph('The annual range used is ' +
        C.pyFixed(seasonal.annual_range_m, 1) + ' m — ' + seasonal.range_source +
        '. It is the one number here that a single test cannot measure, and ' +
        'every figure in the table moves with it.', { italic: true });
      if (seasonal.dry_season_loss_percent > 1) {
        b.paragraph('By the end of the dry season the borehole yields about ' +
          C.pyFixed(seasonal.dry_season_loss_percent, 0) + '% less than it did ' +
          'on the day of the test.', { bold: true });
      }
      b.bullets(seasonal.scenarios.map(function (sc) { return sc.note; }));
      /* the same depth the recommendation printed, not a second one */
      if (pumpDepth !== null) {
        b.paragraph('The pump intake recommended above, ' + C.fmtNum(pumpDepth) +
          ' m ' + DATUM_TEXT + ', is set for the drought case: the pump is fitted ' +
          'once, and one that draws air in a bad year loses the village its ' +
          'borehole in the year it is needed most.', { bold: true });
      }
    }

    b.heading('6. Limitations and Uncertainty', 1);
    limitationsParagraphs('pumping').forEach(function (text) {
      b.paragraph(text, { align: 'justify' });
    });
    b.signOff(context.signOff);
    b.references([REFERENCES.rwsn_professional, REFERENCES.rwsn_supervision]);
    b.glossary(GLOSSARY);
    return b;
  }

  /* --- 4. water quality ------------------------------------------------------ */

  async function qualityReport(context) {
    var b = new ReportBuilder({ style: context.style, title: 'Water Quality Report' });
    var assessment = context.assessment, sample = assessment.sample;
    var site = sample.site || {};
    var figures = context.figures || [];

    b.cover(['Water Quality Report',
      (sample.sample_id ? sample.sample_id + ' — ' : '') + (site.community || '')],
      [], siteDetails(site, [
        ['Sample ID', sample.sample_id || '—'],
        ['Borehole reference', sample.borehole_ref || '—'],
        ['Sample date', sample.sample_date || '—'],
        ['Laboratory', sample.laboratory || '—'],
      ]));
    b.provisionalStamp(context.readiness);
    b.tableOfContents();

    b.executiveSummary([assessment.verdict,
      assessment.corrosivity && assessment.corrosivity.verdict
        ? assessment.corrosivity.verdict : ''],
      [
        assessment.wqi ? 'Water Quality Index: ' + assessment.wqi.value +
          ' (' + assessment.wqi.rating + ')' : null,
        assessment.health_risk ? 'Hazard Index: ' +
          assessment.health_risk.hazard_index + ' — ' + assessment.health_risk.rating : null,
        assessment.ionic ? 'Ionic balance error: ' +
          assessment.ionic.error_percent.toFixed(1) + '%' : null,
        assessment.corrosivity ? 'Corrosivity: ' + assessment.corrosivity.classification : null,
      ]);

    b.heading('1. Sample Details', 1);
    b.keyValueTable([
      ['Sample ID', sample.sample_id || '—'],
      ['Borehole', sample.borehole_ref || '—'],
      ['Sample date', sample.sample_date || '—'],
      ['Laboratory', sample.laboratory || '—'],
      ['Community', site.community || '—'],
      ['District', site.district || '—'],
    ]);

    areaSection(b, context, '1.1 Location and setting');

    b.heading('2. Results Against Guideline Values', 1);
    b.table(assessment.rows.map(function (row) {
      return [row.parameter,
        row.value === null ? (row.below_detection ? '< DL' : '—') : C.fmtNum(row.value, 4),
        row.unit || '', row.who_health || '—', row.sl_standard || '—',
        statusLabel(row.status), row.remark || ''];
    }), {
      header: ['Parameter', 'Result', 'Unit', 'WHO health', 'National', 'Status', 'Remark'],
      caption: 'Laboratory results against WHO and national standards.',
      fontSize: 8.5, colWidthsCm: [3.0, 1.6, 1.4, 1.8, 1.8, 1.9, 4.1],
    });

    /* A national exceedance reads as a compliance failure, so the report has
     * to say plainly when the limit it was judged against is not confirmed. */
    if (C.provisionalNationalParameters().length) {
      b.paragraph(C.PROVISIONAL_NATIONAL_NOTE, { align: 'justify' });
    }

    b.heading('3. Ionic Balance Check', 1);
    if (assessment.ionic) {
      b.paragraph('The charge balance error is ' +
        assessment.ionic.error_percent.toFixed(1) + '% (' +
        assessment.ionic.sum_cations_meq.toFixed(2) + ' meq/L cations against ' +
        assessment.ionic.sum_anions_meq.toFixed(2) + ' meq/L anions). Errors within ' +
        '5% are normal laboratory practice; 5 to 10% warrants review and more ' +
        'than 10% indicates an unreliable analysis or a missing major ion.' +
        (assessment.ionic.used_alkalinity_for_bicarbonate
          ? ' Bicarbonate was derived from the reported alkalinity.' : ''),
        { align: 'justify' });
    } else {
      b.paragraph('The major ions needed for a charge balance (calcium, ' +
        'magnesium, sodium, chloride and bicarbonate or alkalinity) were not all ' +
        'reported, so the balance could not be computed.', { align: 'justify' });
    }

    b.heading('4. Corrosivity and Materials', 1);
    if (assessment.corrosivity) {
      var cor = assessment.corrosivity;
      b.paragraph(cor.verdict, { align: 'justify' });
      if (cor.lsi !== null) {
        b.table([
          ['Langelier Saturation Index (LSI)', String(cor.lsi)],
          ['Ryznar Stability Index (RSI)', String(cor.rsi)],
          ['Aggressive Index (AI)', String(cor.aggressive_index)],
          ['Larson-Skold ratio', cor.larson_skold === null ? '—' : String(cor.larson_skold)],
          ['Classification', cor.classification],
        ], { header: ['Index', 'Value'], caption: 'Corrosivity indices.',
          colWidthsCm: [8.0, 7.6] });
      }
      b.paragraph(cor.materials_note, { align: 'justify' });
      if (cor.assumptions && cor.assumptions.length) b.bullets(cor.assumptions);
    }

    b.heading('5. Hydrochemical Facies', 1);
    /* The section used to be two figures and no words: a reader who cannot
     * read a Piper diagram was told nothing at all by the section named
     * after what it shows. faciesOf names the water type and says what it
     * means, above the diagrams (reporting/quality.py). */
    var facies = C.faciesOf(sample);
    if (facies) b.paragraph(facies.sentence, { align: 'justify' });
    figures.forEach(function (f) { b.figure(f.image, f.caption, f.widthCm || 14); });

    b.heading('6. Recommendations', 1);
    var recommendations = [];
    /* The assessment's own note, rather than a paraphrase of it written
     * here: the two had already drifted apart, and only this copy still
     * spoke of a handpump's rods where the borehole may carry a
     * submersible (reporting/quality.py puts corr.materials_note first). */
    if (assessment.corrosivity && assessment.corrosivity.is_aggressive) {
      recommendations.push(assessment.corrosivity.materials_note);
    }
    if (assessment.health_exceedances.length) {
      recommendations.push('Treat or replace the source before it is used for ' +
        'drinking: ' + assessment.health_exceedances.map(function (r) {
          return r.parameter; }).join(', ') + ' exceed health based limits.');
    }
    if (assessment.national_exceedances.length) {
      recommendations.push('Treat before the supply is accepted against the ' +
        'national standard: ' + assessment.national_exceedances.map(function (r) {
          return r.parameter; }).join(', ') + ' exceed the national limit.');
    }
    if (assessment.verdict_state === 'indeterminate') {
      recommendations.push('Do not describe this supply as safe to drink until ' +
        'the results are complete: ' +
        (assessment.uncertainties || []).join('; ') + '.');
    }
    recommendations.push('Disinfect the borehole after any maintenance and ' +
      're-test microbiological quality before the source is returned to use.');
    recommendations.push('Repeat the analysis at least annually, and after any ' +
      'change in taste, colour or odour.');
    b.bullets(recommendations.concat(context.recommendations || []));

    b.heading('7. Limitations and Uncertainty', 1);
    limitationsParagraphs('quality').forEach(function (text) {
      b.paragraph(text, { align: 'justify' });
    });
    b.signOff(context.signOff);
    b.references([REFERENCES.who, REFERENCES.slsb, REFERENCES.stop_the_rot]);
    b.glossary(GLOSSARY);
    return b;
  }

  function statusLabel(status) {
    /* Every status the assessment can produce has a label here: a row the
     * toolkit could not grade must never reach a client as a raw code. */
    return {
      exceeds_health: 'Exceeds health', exceeds_national: 'Exceeds national',
      exceeds_aesthetic: 'Exceeds acceptability',
      indeterminate: 'NOT EVALUABLE', within_limits: 'Within limits',
      below_detection: 'Below detection', no_guideline: 'No guideline',
      not_measured: 'Not measured',
    }[status] || status;
  }

  /* --- 5. cost estimate ------------------------------------------------------ */

  async function costingReport(context) {
    var b = new ReportBuilder({ style: context.style, title: 'Borehole Cost Estimate' });
    var estimate = context.estimate, site = context.site || {};
    var figures = context.figures || [];

    b.cover(['Borehole Cost Estimate', site.community || ''], [],
      siteDetails(site, [
        ['Total depth', C.fmtNum(estimate.inputs.total_depth_m) + ' m'],
        ['Estimated total cost', S.money(estimate.total_cost_usd, 0)],
        ['Contract price', S.money(estimate.price_usd, 0)],
      ]));
    b.provisionalStamp(context.readiness);
    b.tableOfContents();

    b.executiveSummary([
      'The estimated cost of one ' + C.fmtNum(estimate.inputs.total_depth_m) +
        ' m borehole at ' + (site.community || 'the site') + ' is ' +
        S.money(estimate.total_cost_usd, 0) + ', which is ' +
        S.money(estimate.cost_per_meter_usd, 0) + ' per drilled metre. Adding a ' +
        estimate.margin_percent + '% margin gives a contract price of ' +
        S.money(estimate.price_usd, 0) + '.',
      'The estimate follows the RWSN Borehole Costing Model, which keeps the ' +
        "contractor's cost and the client's price distinct so neither is hidden " +
        'inside the other.',
    ], [
      'Direct works cost: ' + S.money(estimate.direct_cost_usd, 0),
      'Total cost including ' + estimate.overheads_percent + '% overheads: ' +
        S.money(estimate.total_cost_usd, 0),
      'Contract price: ' + S.money(estimate.price_usd, 0),
      'Planning budget with ' + estimate.contingency_percent + '% contingency: ' +
        S.money(estimate.budget_usd, 0),
    ]);

    b.heading('1. Method', 1);
    b.paragraph('The estimate follows the RWSN Borehole Costing Model. Every ' +
      'line item carries a construction stage and a resource category, so the ' +
      'same quantities roll up along both axes. Direct works cost is the sum of ' +
      'the priced quantities; overheads are added to give the total cost; the ' +
      'margin on top of that gives a sustainable contract price. The contingency ' +
      'is a client-side planning allowance and is shown separately so the ' +
      'contract price stays honest.', { align: 'justify' });

    areaSection(b, context, '1.1 Location and setting');

    b.heading('2. Basis of the Estimate', 1);
    b.table([
      ['Total depth', C.fmtNum(estimate.inputs.total_depth_m) + ' m'],
      ['Overburden drilled', C.fmtNum(estimate.inputs.overburden_m) + ' m'],
      ['Bedrock drilled', C.fmtNum(estimate.inputs.bedrock_m) + ' m'],
      ['Plain casing', C.fmtNum(estimate.inputs.casing_m) + ' m'],
      ['Screen', C.fmtNum(estimate.inputs.screen_m) + ' m'],
      ['Gravel pack', C.fmtNum(estimate.inputs.gravel_pack_m3, 3) + ' m³'],
      ['Cement', C.fmtNum(estimate.inputs.cement_bags) + ' bags'],
      ['Crew time', C.fmtNum(estimate.inputs.crew_days) + ' days'],
      ['Mobilisation distance', C.fmtNum(estimate.inputs.mobilisation_distance_km) +
        ' km one way'],
    ], { header: ['Quantity', 'Value'], caption: 'Quantities driving the estimate.',
      colWidthsCm: [7.0, 8.6] });
    if (estimate.assumptions.length) {
      b.paragraph('Assumptions where a figure was not supplied:', { bold: true });
      b.bullets(estimate.assumptions);
    }

    b.heading('3. Bill of Quantities', 1);
    b.table(estimate.boq_rows().map(function (row) {
      return [row.Code, row.Stage, row.Item, row.Unit,
        S.thousands(row.Quantity, 2), S.thousands(row['Rate (USD)'], 2),
        S.thousands(row['Amount (USD)'], 2)];
    }).concat([['', '', 'Direct works cost', '', '', '',
      S.thousands(estimate.direct_cost_usd, 2)]]), {
      header: ['Code', 'Stage', 'Item', 'Unit', 'Qty', 'Rate (US$)', 'Amount (US$)'],
      caption: 'Bill of quantities.', fontSize: 8.5,
      colWidthsCm: [1.3, 1.9, 5.6, 1.5, 1.5, 1.9, 1.9],
    });

    b.heading('4. Cost Summary', 1);
    b.table(C.costSummaryRows(estimate), {
      header: ['Item', 'US$', 'SLE'], caption: 'Cost and price summary.',
      colWidthsCm: [7.0, 4.3, 4.3],
    });
    figures.forEach(function (f) { b.figure(f.image, f.caption, f.widthCm || 15); });

    /* The package roll-up. A programme is budgeted per successful borehole,
     * and the figure that has to be budgeted for carries the dry attempts -
     * which the app could compute and no document it wrote ever said. */
    var section = 5;
    var programme = context.programme;
    if (programme) {
      b.heading(section + '. Programme of Works', 1);
      b.paragraph(programme.n_successful + ' successful ' +
        S.plural(programme.n_successful, 'borehole') + ' at a siting success ' +
        'rate of ' + C.formatG(programme.success_rate_percent) + '% means ' +
        'budgeting for ' + programme.n_attempted + ' ' +
        S.plural(programme.n_attempted, 'attempt') + '. A programme budget ' +
        'that counts only the holes that find water runs out before the last ' +
        'village has any.', { align: 'justify' });
      b.table(C.programmeSummaryRows(programme), {
        header: ['Item', 'US$', 'SLE'],
        caption: 'Programme roll-up, carrying the expected dry attempts.',
        colWidthsCm: [7.0, 4.3, 4.3],
      });
      if (programme.assumptions && programme.assumptions.length) {
        b.paragraph('Assumptions:', { bold: true });
        b.bullets(programme.assumptions);
      }
      section += 1;
    }

    b.heading(section + '. Notes and Exclusions', 1);
    b.bullets([
      'Unit rates are indicative and must be confirmed against current local ' +
        'prices before the estimate is used in a tender.',
      'The exchange rate used for the local currency column is ' +
        estimate.exchange_rate_sle_per_usd + ' SLE per US dollar.',
      'The estimate excludes the client\'s own supervision, land acquisition, ' +
        'community mobilisation and value added tax unless stated.',
      'A dry hole is not costed here; use the programme estimate to carry the ' +
        'expected dry attempts across a package of boreholes.',
    ].concat(context.notes || []));

    b.signOff(context.signOff);
    b.references([REFERENCES.rwsn_cost, REFERENCES.rwsn_pricing, REFERENCES.unicef_toolkit]);
    return b;
  }

  /* --- 6. supervision record ------------------------------------------------- */

  async function supervisionReport(context) {
    var b = new ReportBuilder({ style: context.style, title: 'Supervision Checklist Record' });
    var evaluation = context.evaluation, items = context.items || [];
    var responses = context.responses || {};
    var site = context.site || {};

    b.cover(['Drilling Supervision Record', site.community || ''], [],
      siteDetails(site, [
        ['Borehole reference', context.boreholeRef || '—'],
        ['Items answered', evaluation.answered + ' of ' + evaluation.total],
        ['Critical failures', String(evaluation.critical_failures)],
      ]));
    b.provisionalStamp(context.readiness);

    b.heading('1. Summary', 1);
    b.paragraph(evaluation.verdict, { bold: true });
    b.table(evaluation.stages.map(function (stage) {
      return [stage.title, String(stage.total), String(stage.answered),
        String(stage.passed), String(stage.failed), String(stage.critical_failed),
        stage.percent.toFixed(0) + '%'];
    }), {
      header: ['Stage', 'Items', 'Answered', 'Satisfied', 'Failed', 'Critical failed',
        'Progress'],
      caption: 'Checklist progress by stage.', fontSize: 9,
    });

    areaSection(b, context, '1.1 Location and setting');

    b.heading('2. Checklist Record', 1);
    evaluation.stages.forEach(function (stage) {
      var stageItems = items.filter(function (i) { return i.checklist === stage.stage; });
      if (!stageItems.length) return;
      b.heading(stage.title, 2);
      b.table(stageItems.map(function (item) {
        var response = responses[item.item_id] || {};
        return [item.section, item.text, item.critical ? 'Yes' : '',
          (response.status || 'pending').toUpperCase(), response.remark || ''];
      }), {
        header: ['Section', 'Requirement', 'Critical', 'Answer', 'Remark'],
        fontSize: 8.5, colWidthsCm: [2.6, 6.6, 1.4, 1.7, 3.3],
      });
    });

    b.heading('3. Site Notes and Instructions', 1);
    if ((context.notes || []).length) b.bullets(context.notes);
    else b.paragraph('No additional site instructions were recorded.');

    if (context.fieldChecks && context.fieldChecks.length) {
      b.table(context.fieldChecks.map(function (check) {
        return [check.name, check.measured, check.limit,
          check.status.toUpperCase(), check.message];
      }), {
        header: ['Check', 'Measured', 'Acceptance limit', 'Result', 'Note'],
        caption: 'Field acceptance checks.', fontSize: 8.5,
        colWidthsCm: [3.0, 2.8, 3.4, 1.6, 4.8],
      });
    }

    /* the supervisor's photographs: taken to be evidence, so they belong in
     * the record rather than in the project file alone */
    var figures = context.figures || [];
    if (figures.length) {
      b.heading('3.1 Photographic record', 2);
      figures.forEach(function (f) {
        b.figure(f.image, f.caption, f.widthCm || 13);
      });
    }

    b.heading('4. Sign Off', 1);
    b.signatures(['Supervisor', 'Drilling contractor', 'Client representative']);
    b.references([REFERENCES.rwsn_supervision, REFERENCES.unicef_toolkit]);
    return b;
  }

  /* --- 7. project handover --------------------------------------------------- */

  /* The care a handpump needs: rods to tighten, strokes to count, a pump
   * head to inspect. groundwater/reporting/handover.py _OM_GUIDANCE. */
  var OM_GUIDANCE = [
    ['Daily', [
      'Keep the apron and surroundings clean; no washing or animal watering ' +
        'on the apron.',
      'Check for leaks, unusual pump noise and discoloured water.',
      'Keep the drainage channel and soakaway free flowing.',
    ]],
    ['Weekly', [
      'Tighten loose bolts on the pump head and inspect the apron for cracks.',
      'Record the approximate hours of use or strokes per day.',
    ]],
    ['Monthly', [
      'Measure and record the water level where a dip access exists.',
      'Collect the agreed user fees and update the cash book.',
      'Inspect the fence and the sanitary protection zone (no pit latrine, ' +
        'refuse pit or animal pen within 30 m).',
    ]],
    ['Yearly', [
      'Service the pump according to the manufacturer schedule and replace ' +
        'fast wearing parts.',
      'Repeat the physico-chemical and bacteriological water tests.',
      'Review the tariff against the cost of spare parts.',
    ]],
  ];

  /* The same care for a submersible or solar pump, which has no pump rods
   * and no strokes to count. The handpump list used to go out with a
   * recorded submersible pump. _OM_GUIDANCE_MOTORISED in handover.py. */
  var OM_GUIDANCE_MOTORISED = [
    ['Daily', [
      'Keep the pump house, apron and surroundings clean; no washing or ' +
        'animal watering at the tap stand.',
      'Check for leaks, unusual pump or motor noise, discoloured water and ' +
        'a falling flow.',
      'Keep the drainage channel and soakaway free flowing.',
    ]],
    ['Weekly', [
      'Record the hours of pumping and the meter reading, if fitted.',
      'Check the control box, cables, starter and (for a solar pump) the ' +
        'array for damage, loose connections and shading.',
    ]],
    ['Monthly', [
      'Measure and record the water level where a dip access exists.',
      'Collect the agreed user fees and update the cash book.',
      'Inspect the fence and the sanitary protection zone (no pit latrine, ' +
        'refuse pit or animal pen within 30 m).',
      'Check the running current against the commissioning value.',
    ]],
    ['Yearly', [
      'Service the pump and motor according to the manufacturer schedule; ' +
        'check the rising main and cable for corrosion and wear.',
      'Repeat the physico-chemical and bacteriological water tests.',
      'Review the tariff against the cost of spare parts and power.',
    ]],
  ];

  /* The care list for the pump that was actually installed, by the same
   * words handover.py om_guidance matches on. */
  function omGuidance(pumpType) {
    var kind = String(pumpType || '').toLowerCase();
    var motorised = ['submersible', 'solar', 'motor', 'electric'];
    for (var i = 0; i < motorised.length; i++) {
      if (kind.indexOf(motorised[i]) >= 0) return OM_GUIDANCE_MOTORISED;
    }
    return OM_GUIDANCE;
  }

  /* The works list, built only from the records the project actually holds.
   *
   * This document is signed by the contractor, the client and the community,
   * so it must not assert a pumping test, a laboratory analysis or a handpump
   * that nobody supplied - a signature under a works list is what an interim
   * payment is later argued from. It is the same reason each bullet names its
   * method and carries its quantity: what a quantity surveyor checks is the
   * drilled depth, the screen run and the seal.
   *
   * groundwater/reporting/handover.py builds the same list from the same
   * records, and tests/webapp/parity.mjs holds the two to the same words, so
   * a reworded bullet here is a reworded bullet there. They used to differ in
   * four of seven bullets, which handed one borehole two different
   * certificates: a surveyor got the casing size or the screen run, never
   * both, and never the seal. */
  function handoverWorks(context) {
    var log = context.log || {}, design = context.design;
    var works = [];
    if (context.interpretations && context.interpretations.length) {
      works.push('Geophysical siting survey and borehole location selection.');
    }
    /* the depth is the first quantity anyone measures the claim against, so
     * the bullet waits for one rather than certifying a borehole drilled to
     * "n/a" off a sheet where nobody wrote the depth down */
    if (log.total_depth_m !== null && log.total_depth_m !== undefined) {
      works.push('Drilling of the borehole to ' + C.fmtNum(log.total_depth_m) +
        ' m' + (log.drilling_method ? ' by ' + log.drilling_method : '') + '.');
    }
    if (design) {
      works.push('Construction with ' + C.formatG(design.casing_diameter_in) +
        ' inch ' + design.casing_material + ' casing, ' +
        C.fmtNum(design.total_screen_length_m) + ' m of screen, gravel pack ' +
        'and sanitary seal to ' + C.fmtNum(design.sanitary_seal[1]) + ' m.');
      works.push('Development of the borehole by air lifting until clear.');
    }
    if (context.analysis) works.push('Pumping test and yield assessment.');
    if (context.assessment) {
      works.push('Water quality sampling and laboratory analysis.');
    }
    /* No wellhead bullet: the toolkit holds no headworks record for it to be
     * conditioned on, and an unconditional one certified an apron and a
     * drainage channel on every borehole. A supervisor who built them says so
     * through the works notes. */
    return works;
  }

  async function handoverReport(context) {
    var b = new ReportBuilder({ style: context.style, title: 'Project Handover Report' });
    var site = context.site || {}, log = context.log || {}, design = context.design;
    var analysis = context.analysis, assessment = context.assessment;
    var figures = context.figures || [];
    var rec = analysis ? analysis.yield_recommendation : null;
    /* the design's intake where there is one: it may have moved the yield's
     * depth out of a screen into plain casing (handover.py) */
    var intake = design && design.pump_intake_m ? design.pump_intake_m
      : (rec ? rec.pump_installation_depth_m : null);

    b.cover(['Project Handover Report', site.community || ''], [],
      siteDetails(site, [
        ['Borehole reference', log.borehole_ref || context.boreholeRef || '—'],
        ['Handover date', context.handoverDate || ''],
      ]));
    b.provisionalStamp(context.readiness);
    b.tableOfContents();

    b.executiveSummary([
      'A borehole has been completed and equipped at ' + (site.community || 'the site') +
        ' and is handed over to the community for operation and maintenance.',
      rec && rec.safe_yield_m3_per_h
        ? 'The source is rated at a safe yield of ' + C.yieldRangeText(rec) +
          (rec.is_indicative ? ' (indicative)' : '') +
          ', which is sufficient for about ' +
          Math.round(rec.safe_yield_m3_per_h * 1000 * 8 / 20) +
          ' people at 20 litres per person per day over an eight hour pumping day.' +
          /* a 30-minute test inside its casing storage cannot become
           * "sustainable" on the handover certificate */
          (rec.is_indicative ? ' ' + rec.confidence_text : '')
        : '',
      assessment ? assessment.verdict : '',
    ], [
      log.total_depth_m ? 'Depth: ' + C.fmtNum(log.total_depth_m) + ' m' : null,
      rec && rec.safe_yield_m3_per_h ? 'Safe yield: ' + C.yieldRangeText(rec) +
        (rec.is_indicative ? ' (indicative)' : '') : null,
      intake ? 'Pump intake: ' + C.fmtNum(intake) + ' m below the top of the casing' : null,
      assessment
        ? 'Water quality: ' + C.VERDICT_LONG[assessment.verdict_state].toLowerCase()
        : null,
    ]);

    b.heading('1. Project Summary', 1);
    b.keyValueTable(siteDetails(site));

    areaSection(b, context, '1.1 Location and setting');

    b.heading('2. Works Completed', 1);
    b.bullets(handoverWorks(context).concat(context.worksNotes || []));

    b.heading('3. Borehole Data Sheet', 1);
    /* Assembled from the records themselves rather than from a fixed list,
     * as handover.py does, so the sheet carries the drilling method, the
     * strikes, the whole construction summary and the pump that was
     * installed instead of a handful of headline figures. */
    var dataRows = [];
    if (context.log) {
      dataRows.push(['Borehole reference', log.borehole_ref || context.boreholeRef || '—']);
      dataRows.push(['Total depth',
        log.total_depth_m ? C.fmtNum(log.total_depth_m) + ' m' : '—']);
      dataRows.push(['Drilling method', log.drilling_method || '—']);
      dataRows.push(['Water strikes', (log.water_strikes_m || []).length
        ? log.water_strikes_m.map(function (w) { return C.formatG(w) + ' m'; }).join(', ')
        : 'n/a']);
      dataRows.push(['Completion date', log.completion_date || '—']);
      dataRows.push(['Status', log.status || '—']);
    }
    if (design) dataRows = dataRows.concat(C.designSummaryRows(design));
    if (analysis) {
      if (analysis.transmissivity_m2_per_day) {
        dataRows.push(['Transmissivity',
          C.fmtNum(analysis.transmissivity_m2_per_day) + ' m2/day']);
      }
      /* handover.py nests both inside "if yr is not None": an intake with no
       * yield recommendation behind it is a depth the test never supported. */
      if (rec) {
        if (rec.safe_yield_m3_per_h) {
          dataRows.push(['Safe yield (safety factor ' + C.formatG(rec.safety_factor) + ')',
            C.yieldRangeText(rec) + (rec.is_indicative ? ' (indicative)' : '')]);
          dataRows.push(['Yield confidence', rec.is_indicative
            ? 'indicative: ' + rec.confidence_reasons.join('; ') : 'established']);
        }
        if (intake) {
          dataRows.push(['Pump intake depth',
            C.fmtNum(intake) + ' m below the top of the casing']);
        }
      }
    }
    if (context.pumpType) dataRows.push(['Pump type', context.pumpType]);
    /* One row per item: the log and the design both carry a total depth, a
     * static level and the strikes, and the sheet printed each of them
     * twice, a metre apart, for a reader to reconcile. */
    var seenRows = {};
    dataRows = dataRows.filter(function (row) {
      if (seenRows[row[0]]) return false;
      seenRows[row[0]] = true;
      return true;
    });
    b.table(dataRows, { header: ['Item', 'Value'],
      caption: 'Borehole data sheet.', colWidthsCm: [6.0, 9.6] });
    /* handover.py: the drawing is an as-built diagram only when the screens
     * are the ones the log records as installed; then the design's warnings */
    var designFig = design ? designFigure(figures) : null;
    if (design && designFig) {
      b.figure(designFig.image, design.as_built
        ? 'As-built borehole diagram.'
        : 'Borehole construction design generated from the drilling log; ' +
          'the log records no casing string, so this is not an as-built record.',
        designFig.widthCm || 14);
    }
    if (design) designNotes(b, design);
    figures.forEach(function (f) {
      if (f !== designFig) b.figure(f.image, f.caption, f.widthCm || 14);
    });

    b.heading('4. Water Quality', 1);
    if (assessment) {
      b.paragraph(assessment.verdict, { align: 'justify' });
      /* Every exceedance, national ones included: a national breach is a
       * compliance failure and belongs in the document that hands the
       * source over, not only in the quality report (handover.py). */
      var breaches = assessment.all_exceedances || [];
      if (breaches.length) {
        b.table(breaches.map(function (r) {
          return [r.parameter, C.fmtNum(r.value), r.unit || '', r.remark || ''];
        }), {
          header: ['Parameter', 'Value', 'Unit', 'Remark'],
          caption: 'Parameters above guideline or standard limits.',
          fontSize: 9, colWidthsCm: [3.8, 1.8, 1.8, 8.2],
        });
        /* A national limit the quality report calls provisional is
         * provisional on the handover certificate too. */
        if (C.provisionalNationalParameters().length) {
          b.paragraph(C.PROVISIONAL_NATIONAL_NOTE, { align: 'justify', italic: true });
        }
      }
    } else {
      b.paragraph('No water quality analysis was available at handover. Sample ' +
        'the source and have it analysed before the supply is used for drinking.',
        { align: 'justify' });
    }

    b.heading('5. Operation and Maintenance Guidance', 1);
    b.paragraph('The lifetime of the borehole depends on routine care. The ' +
      'tasks below follow standard rural water supply practice; the community ' +
      'should keep a logbook of all maintenance, breakdowns and payments.',
      { align: 'justify' });
    /* The tasks follow the pump that was installed. This section used to
     * hard-code handpump care - bolts on the pump head, strokes per day -
     * and went out unchanged over a data sheet recording a submersible,
     * which has neither (handover.py om_guidance). */
    omGuidance(context.pumpType).forEach(function (period) {
      b.paragraph(period[0], { bold: true });
      b.bullets(period[1]);
    });
    if (rec && rec.safe_yield_m3_per_h) {
      b.paragraph('Operate the pump at no more than ' +
        C.fmtNum(rec.safe_yield_m3_per_h) + ' m3/h and allow the recommended ' +
        'rest periods. If the water level reaches the pump intake, stop ' +
        'pumping and let the borehole recover.', { bold: true });
    }
    if (context.tariffNote) b.paragraph('Tariff arrangement: ' + context.tariffNote);
    if ((context.omNotes || []).length) b.bullets(context.omNotes);

    b.heading('6. Community / WASH Committee', 1);
    if ((context.committee || []).length) {
      b.table(context.committee.map(function (member) {
        return [member.name || '', member.role || '', member.contact || ''];
      }), { header: ['Name', 'Role', 'Contact'],
        caption: 'Water and sanitation committee.', colWidthsCm: [5.5, 5.0, 5.1] });
    } else {
      b.paragraph('The water and sanitation committee members are to be recorded ' +
        'at handover.', { align: 'justify' });
    }

    b.heading('7. Recommendations', 1);
    b.bullets((context.recommendations || []).length ? context.recommendations : [
      'Re-test the water quality within three months of commissioning and at ' +
        'least annually thereafter.',
      'Agree and collect a tariff sufficient to cover routine maintenance and ' +
        'an eventual pump replacement.',
      'Register the source with the district water office so it appears in the ' +
        'national inventory.',
    ]);

    b.heading('8. Handover Signatures', 1);
    b.signatures(['Client representative', 'Community / committee chair',
      'Contractor', 'District water office']);
    b.signOff(context.signOff);
    b.references([REFERENCES.rwsn_professional, REFERENCES.who, REFERENCES.slsb,
      REFERENCES.unicef_toolkit]);
    b.glossary(GLOSSARY);
    return b;
  }

  /* --- the asset registry --------------------------------------------------
   * Two documents. The placard is one page to print, laminate and fix to the
   * headworks: the identifier in large type, the symbol that encodes it, and
   * the facts that do not go out of date. The record is the history, and what
   * that history says the borehole's condition is today.
   * ---------------------------------------------------------------------- */

  async function assetPlacard(context) {
    var asset = context.asset;
    var b = new ReportBuilder({ style: context.style,
      title: 'Borehole ' + asset.asset_id });
    var state = context.state || C.assetState(asset, context.today);

    b.paragraph('BOREHOLE IDENTIFICATION PLATE', { bold: true, align: 'center' });
    b.paragraph(asset.asset_id, { bold: true, size: 26, align: 'center' });
    b.paragraph(C.assetLabel(asset), { size: 13, align: 'center' });
    if (context.symbol) {
      b.figure(context.symbol, 'Scan for this borehole’s identifier and ' +
        'position. The symbol carries the details themselves, so it reads with ' +
        'no network and no application installed.', 7.0);
    }
    b.table(C.placardLines(asset, state), {
      header: ['', ''], caption: 'Borehole details.', colWidthsCm: [5.0, 10.0] });
    b.paragraph('Report a breakdown or a change to this borehole against the ' +
      'identifier above. Quote it in full, including the last character — ' +
      'it is a check character, and it is what stops a repair being recorded ' +
      "against a different village's borehole.", { italic: true });
    return b;
  }

  async function assetRecordReport(context) {
    var asset = context.asset;
    var state = context.state || C.assetState(asset, context.today);
    var today = context.today || new Date().toISOString().slice(0, 10);
    var b = new ReportBuilder({ style: context.style,
      title: 'Asset record - ' + C.assetLabel(asset) });

    b.cover(['Borehole Asset Record'], [C.assetLabel(asset), asset.asset_id],
      [['Status', state.label], ['As at', today]]);
    b.provisionalStamp(context.readiness);

    b.heading('Condition', 1);
    b.paragraph(state.label + '. ' + state.detail);
    if (state.days_out_of_service !== null && state.days_out_of_service !== undefined) {
      b.paragraph('This borehole has been out of service for ' +
        state.days_out_of_service + ' days. Every day counted here is a day ' +
        'the community went back to whatever they used before.', { bold: true });
    }
    if (state.undated_events) {
      b.paragraph(state.undated_events + ' ' +
        S.plural(state.undated_events, 'record') + ' ' +
        (state.undated_events === 1 ? 'carries' : 'carry') + ' a date that could ' +
        'not be read. They are listed below with the date as written, but they ' +
        'establish nothing about when anything last happened.');
    }

    /* the record is what a district water office reads before it decides
     * where to send a repair team */
    areaSection(b, context, 'Where it is');

    b.heading('Details', 1);
    b.table(C.placardLines(asset, state),
      { header: ['', ''], colWidthsCm: [5.0, 10.0] });

    b.heading('Outstanding', 1);
    var outstanding = state.due.filter(function (item) {
      return item.state === 'overdue' || item.state === 'unknown';
    });
    var scheduled = state.due.filter(function (item) {
      return item.state === 'scheduled' || item.state === 'due';
    });
    if (outstanding.length) {
      b.bullets(outstanding.map(function (item) { return item.detail; }));
    } else if (scheduled.length) {
      b.bullets(scheduled.map(function (item) { return item.detail; }));
    } else {
      b.paragraph('Nothing is outstanding.');
    }

    b.heading('History', 1);
    var events = (asset.events || []).slice().sort(function (a, c) {
      var aw = a.when || '9999', cw = c.when || '9999';
      if (aw !== cw) return aw < cw ? -1 : 1;
      return a.kind < c.kind ? -1 : (a.kind > c.kind ? 1 : 0);
    });
    if (events.length) {
      b.table(events.map(function (e) {
        return [e.when || '(no date)', C.eventLabel(e.kind), e.note || '',
          e.by || '', e.photo ? 'yes' : ''];
      }), {
        header: ['Date', 'Event', 'Note', 'Recorded by', 'Photo'],
        caption: 'Everything recorded against this borehole.',
        colWidthsCm: [2.4, 3.2, 6.0, 2.4, 1.5],
      });
      b.paragraph('This history is append-only: a mistake is corrected by ' +
        'recording the correction, so both entries stay visible. Nothing here ' +
        'has been edited or removed.', { italic: true });
    } else {
      b.paragraph('Nothing has ever been recorded against this borehole. That ' +
        'is not the same as nothing having happened to it.', { bold: true });
    }
    return b;
  }

  /* --- the interim payment certificate --------------------------------------
   * The document a contractor is paid against, so everything that reduces
   * the payment appears on its face with its own line. A certificate showing
   * only the bottom figure is one nobody can check, and one nobody can check
   * is one nobody can dispute.
   * ---------------------------------------------------------------------- */

  async function paymentCertificate(context) {
    var contract = context.contract, certificate = context.certificate;
    var b = new ReportBuilder({ style: context.style,
      title: 'Interim Payment Certificate ' + certificate.number });

    b.cover(['Interim Payment Certificate No. ' + certificate.number],
      [contract.ref, contract.contractor || ''],
      [['Date', certificate.date || '—'],
        ['Due on this certificate', C.money0(certificate.due_now_usd)]]);
    b.provisionalStamp(context.readiness);

    if (certificate.problems.length) {
      b.heading('Before the figures', 1);
      b.paragraph('The valuation below could not be made cleanly. Each item ' +
        'here reduces or holds back money, and the certificate is issued with ' +
        'them showing rather than resolved silently.', { bold: true });
      b.bullets(certificate.problems);
    }

    /* the works being paid for are at a place */
    areaSection(b, context, 'Where the works are');

    b.heading('Summary', 1);
    b.table(C.contractSummaryRows(contract, certificate),
      { header: ['', ''], colWidthsCm: [8.0, 7.0] });
    if (certificate.overpaid_usd) {
      b.paragraph('Certificates already issued exceed the value of the work ' +
        'by ' + C.money0(certificate.overpaid_usd) + '. Nothing is due on ' +
        'this certificate. Recovering the difference is a credit note to be ' +
        'agreed, not a negative payment.', { bold: true });
    }

    b.heading('Measurement', 1);
    b.table(certificate.lines.map(function (line) {
      return [line.code, line.item, line.unit,
        C.formatG(line.contract_quantity),
        line.variation_quantity
          ? (line.variation_quantity > 0 ? '+' : '') +
            C.formatG(line.variation_quantity) : '—',
        C.formatG(line.measured_quantity), C.formatG(line.payable_quantity),
        C.thousandsFixed(line.rate_usd, 2),
        C.thousandsFixed(C.pyRound(line.payable_amount_usd, 0), 0)];
    }), {
      header: ['Code', 'Item', 'Unit', 'Contract', 'Varied', 'Measured',
        'Payable', 'Rate (USD)', 'Amount (USD)'],
      caption: 'Work measured to date and what is payable on it.',
      colWidthsCm: [1.6, 4.2, 1.2, 1.6, 1.4, 1.6, 1.5, 1.6, 1.8],
      fontSize: 8.5,
    });

    var over = certificate.lines.filter(function (line) {
      return line.overmeasure_quantity > 0;
    });
    if (over.length) {
      b.heading('Measured beyond what was authorised', 1);
      b.paragraph('The quantities below have been done but not authorised, so ' +
        'they are not certified here. That is not a judgement on whether the ' +
        'work was necessary — it usually was — but on whether anybody has yet ' +
        'signed for it. A variation order authorising them makes them payable ' +
        'on the next certificate.', { align: 'justify' });
      b.table(over.map(function (line) {
        return [line.code, line.item,
          C.formatG(line.authorised_quantity) + ' ' + line.unit,
          C.formatG(line.measured_quantity) + ' ' + line.unit,
          C.formatG(line.overmeasure_quantity) + ' ' + line.unit,
          C.thousandsFixed(C.pyRound(line.overmeasure_amount_usd, 0), 0)];
      }), {
        header: ['Code', 'Item', 'Authorised', 'Measured', 'Excess',
          'Value withheld (USD)'],
        colWidthsCm: [1.8, 4.6, 2.4, 2.4, 2.0, 2.4],
      });
      b.paragraph('Total value measured but not certified: ' +
        C.money0(certificate.overmeasure_usd) + '.', { bold: true });
    }

    var varied = certificate.lines.filter(function (line) {
      return line.variation_refs && line.variation_refs.length;
    });
    if (varied.length) {
      b.heading('Variations included', 1);
      b.table(varied.map(function (line) {
        var value = line.authorised_amount_usd - line.contract_amount_usd;
        return [line.variation_refs.join(', '), line.code, line.item,
          (line.variation_quantity > 0 ? '+' : '') +
            C.formatG(line.variation_quantity) + ' ' + line.unit,
          (value >= 0 ? '+' : '-') +
            C.thousandsFixed(C.pyRound(Math.abs(value), 0), 0)];
      }), {
        header: ['Reference', 'Code', 'Item', 'Quantity', 'Value (USD)'],
        colWidthsCm: [2.4, 1.8, 5.6, 2.6, 3.2],
      });
    }

    b.heading('Certification', 1);
    b.paragraph('The work described above has been measured and valued at ' +
      C.money0(certificate.gross_usd) + '. After retention and previous ' +
      'certificates, ' + C.money0(certificate.due_now_usd) + ' is due to ' +
      (contract.contractor || 'the contractor') + ' on this certificate.');
    b.signatures(['Supervising engineer', 'Contractor', 'Client']);
    b.signOff(context.signOff);
    return b;
  }

  GWT.docx = {
    ReportBuilder: ReportBuilder,
    geophysicalReport: geophysicalReport,
    completionReport: completionReport,
    pumpingReport: pumpingReport,
    qualityReport: qualityReport,
    costingReport: costingReport,
    supervisionReport: supervisionReport,
    handoverReport: handoverReport, handoverWorks: handoverWorks,
    assetPlacard: assetPlacard, assetRecordReport: assetRecordReport,
    paymentCertificate: paymentCertificate,
    REFERENCES: REFERENCES, GLOSSARY: GLOSSARY, statusLabel: statusLabel,
  };
}(typeof window !== 'undefined' ? window : globalThis));

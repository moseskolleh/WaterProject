/* gwt-docx.js - the seven house-styled .docx reports, written in the browser.
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
    if (details && details.length) {
      this.keyValueTable(details);
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
      caption: 'Decisions recorded against this borehole',
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
    bgs: 'British Geological Survey (2019). Africa Groundwater Atlas: Hydrogeology ' +
      'of Sierra Leone. BGS, Keyworth (CC BY-SA 4.0).',
    stop_the_rot: 'RWSN (2021). Stop the Rot: Handpump Corrosion and Premature ' +
      'Failure in Sub-Saharan Africa. Rural Water Supply Network, St Gallen.',
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
      pairs.push(['GPS easting', C.fmtNum(site.easting, 7)]);
      pairs.push(['GPS northing', C.fmtNum(site.northing, 7)]);
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

  function limitationsParagraphs(kind) {
    var shared = 'The findings rest on the data recorded on the field sheets and ' +
      'on the standard interpretation methods named in this report. Field data ' +
      'carry measurement error, and the methods carry assumptions that are ' +
      'stated where they are used.';
    if (kind === 'ves') {
      return [shared, 'Resistivity models are not unique: different layer ' +
        'combinations can fit the same sounding curve almost equally well ' +
        '(the equivalence and suppression problem), and the depth of ' +
        'investigation is limited by the maximum electrode spacing used. The ' +
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

    var best = interpretations.slice().sort(function (a, c) {
      return (a.rank || 99) - (c.rank || 99);
    })[0];
    b.executiveSummary([
      'A vertical electrical sounding survey was carried out at ' +
        (site.community || 'the site') + ' to select a drilling target. ' +
        interpretations.length + ' ' + S.plural(interpretations.length, 'sounding') +
        ' were made and interpreted as layered earth models.',
      best ? 'The recommended drilling point is ' + best.sounding_id + ', where ' +
        (best.water_zones.length
          ? 'possible water bearing zones are resolved between ' +
            best.water_zones.map(function (z) {
              return Math.trunc(z[0]) + ' m and ' + Math.trunc(z[1]) + ' m'; }).join(', ')
          : 'no clear water bearing zone was resolved') +
        '. A maximum drilling depth of ' + best.max_drilling_depth_m.toFixed(0) +
        ' m is recommended.' : '',
    ], best ? [
      'Recommended VES point: ' + best.sounding_id,
      'Depth to bedrock: ' + (best.depth_to_basement_m !== null
        ? C.fmtNum(best.depth_to_basement_m) + ' m' : 'not resolved'),
      'Total interpreted aquifer thickness: ' + C.fmtNum(best.aquifer_thickness_m) + ' m',
      'Aquifer protective capacity: ' + best.protective_capacity,
      'Recommended maximum drilling depth: ' + best.max_drilling_depth_m.toFixed(0) + ' m',
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
    b.paragraph(context.geologyNote || 'The area lies within the crystalline ' +
      'basement complex of Sierra Leone. Groundwater in this terrain occurs in ' +
      'the weathered overburden (saprolite and saprock) and in the fractured ' +
      'zone at the top of fresh bedrock. Yields depend on the thickness of the ' +
      'weathered zone and on the degree of fracturing, both of which vary over ' +
      'short distances, which is why a geophysical survey precedes drilling.',
      { align: 'justify' });

    b.heading('3. Field Work', 1);
    b.heading('3.1 Reconnaissance Survey', 2);
    b.paragraph('The site was walked with the community to identify candidate ' +
      'points clear of latrines, graveyards, refuse pits and flood paths, and ' +
      'accessible to a drilling rig.', { align: 'justify' });
    b.heading('3.2 Geophysical Survey', 2);
    b.heading('3.2.1 Resistivity Profiling', 3);
    b.paragraph('Resistivity measurements were made with a Schlumberger array. ' +
      'Apparent resistivity is computed from the measured resistance and the ' +
      'array geometric factor.', { align: 'justify' });
    b.heading('3.2.2 Selection of VES Points', 3);
    b.paragraph('Sounding points were placed on the candidate positions agreed ' +
      'with the community.', { align: 'justify' });
    b.heading('3.2.3 Vertical Electrical Sounding (VES)', 3);
    b.paragraph('Each sounding was expanded to a maximum AB/2 of ' +
      (interpretations.length
        ? C.fmtNum(Math.max.apply(null, interpretations.map(function (i) {
            return i.investigation_depth_m; })))
        : '—') + ' m, which sets the depth of investigation.', { align: 'justify' });

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
        caption: 'Layered model for ' + interp.sounding_id,
        colWidthsCm: [1.4, 2.6, 2.2, 1.8, 1.8, 6.2],
      });
      var fig = figures.filter(function (f) { return f.soundingId === interp.sounding_id; });
      for (var k = 0; k < fig.length; k++) {
        b.figure(fig[k].image, fig[k].caption, fig[k].widthCm || 15);
      }
    }

    if (interpretations.length) {
      b.heading('Drill-target suitability', 2);
      b.table(C.drillingPreferenceTable(interpretations, context.preferredOrder)
        .map(function (row) {
          return [row['No.'], row['VES Point'], row.Layer, row['Thickness (m)'],
            row['Depth (m)'], row['Apparent Resistivity (Ohm-m)'],
            row['Possible Water Zones (m)'], row['Max Drilling Depth (m)'], row.Ranking];
        }), {
        header: ['No.', 'VES Point', 'Layer', 'Thickness (m)', 'Depth (m)',
          'Resistivity (Ω·m)', 'Possible water zones (m)', 'Max depth', 'Ranking'],
        caption: 'Ranked drilling preference',
        fontSize: 8.5,
      });
    }

    b.heading('5. Conclusions and Recommendations', 1);
    if (best) {
      b.bullets([
        'Drill at ' + best.sounding_id + ' (ranked ' + C.ordinal(best.rank || 1) + ').',
        'Recommended maximum drilling depth: ' + best.max_drilling_depth_m.toFixed(0) + ' m.',
        best.water_zones.length
          ? 'Target the interpreted water bearing zone(s) at ' +
            best.water_zones.map(function (z) {
              return Math.trunc(z[0]) + '–' + Math.trunc(z[1]) + ' m'; }).join(', ') + '.'
          : 'No clear water bearing zone was resolved; treat the hole as exploratory.',
        'Case and screen against the zones confirmed by the drill cuttings, not ' +
          'against this model alone.',
      ]);
    }
    (context.recommendations || []).length && b.bullets(context.recommendations);

    b.heading('6. Limitations and Uncertainty', 1);
    limitationsParagraphs('ves').forEach(function (text) {
      b.paragraph(text, { align: 'justify' });
    });

    if (context.verificationNotes && context.verificationNotes.length) {
      b.heading('Annex A. Data Verification Notes', 1);
      b.bullets(context.verificationNotes);
    }

    b.references([REFERENCES.rwsn_professional, REFERENCES.geology, REFERENCES.bgs]);
    b.glossary(GLOSSARY);
    return b;
  }

  /* --- 2. borehole completion ------------------------------------------------ */

  async function completionReport(context) {
    var b = new ReportBuilder({ style: context.style, title: 'Borehole Completion Report' });
    var site = context.site || {}, log = context.log || {}, design = context.design;
    var figures = context.figures || [];

    b.cover(['Borehole Completion Report',
      (log.borehole_ref ? log.borehole_ref + ' — ' : '') + (site.community || '')],
      [], siteDetails(site, [
        ['Borehole reference', log.borehole_ref || '—'],
        ['Total depth', log.total_depth_m ? C.fmtNum(log.total_depth_m) + ' m' : '—'],
        ['Drilling method', log.drilling_method || '—'],
        ['Status', log.status || '—'],
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
      design ? 'The borehole was completed with ' + C.fmtNum(design.total_screen_length_m) +
        ' m of screen in ' + design.screens.length + ' ' +
        S.plural(design.screens.length, 'section') + ', gravel packed from ' +
        design.gravel_pack[0].toFixed(0) + ' m to the bottom and sealed with cement ' +
        'grout from surface to ' + design.sanitary_seal[1].toFixed(0) + ' m.' : '',
    ], [
      log.status ? 'Outcome: ' + log.status : null,
      log.total_depth_m ? 'Total depth: ' + C.fmtNum(log.total_depth_m) + ' m' : null,
      design ? 'Screened interval(s): ' + design.screens.map(function (s) {
        return s.top_m.toFixed(1) + '–' + s.bottom_m.toFixed(1) + ' m'; }).join(', ') : null,
    ]);

    b.heading('1. Introduction', 1);
    b.paragraph('This report records the drilling and construction of borehole ' +
      (log.borehole_ref || '') + ' at ' + (site.community || 'the project site') +
      '. It presents the drilling log, the construction details and the ' +
      'as-built design.', { align: 'justify' });

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
      caption: 'Drilling log', colWidthsCm: [2.6, 2.4, 8.6, 2.0],
    });

    b.heading('5. Borehole Construction', 1);
    if (design) {
      b.table(C.designSummaryRows(design), {
        header: ['Item', 'Detail'], caption: 'As-built construction summary',
        colWidthsCm: [5.0, 10.6],
      });
      b.bullets(design.design_basis);
    }
    figures.forEach(function (f) { b.figure(f.image, f.caption, f.widthCm || 13); });

    /* Sections 6 to 9, which the Python builder has always written and this
     * one stopped short of. A completion report that ends at the casing
     * schedule does not say what the borehole yields, how the pump sits in
     * it, whether the water is drinkable or what anyone should do next -
     * which is most of what the client reads it for. */
    var analysis = context.analysis || null;
    var assessment = context.assessment || null;
    var test = analysis ? analysis.test : null;
    var rec = analysis ? analysis.yield_recommendation : null;
    var section = 6;

    if (analysis) {
      b.heading(section + '. Pumping Test', 1);
      var steps = (test && test.steps) || [];
      var last = steps.length ? steps[steps.length - 1] : null;
      /* the maximum drawdown is measured at the end of the last step, so the
       * rate quoted beside it has to be that step's, not step one's */
      var q = last ? last.discharge_m3_per_h : null;
      var rows = [
        ['Test type', (test && test.test_type) || '—'],
        ['Duration', test && test.pumping_duration_min
          ? C.fmtNum(test.pumping_duration_min) + ' min' : '—'],
        [steps.length > 1 ? 'Discharge (final step)' : 'Discharge',
          q ? C.fmtNum(q) + ' m3/h' : 'pending'],
        ['Static water level', test && test.static_water_level_m !== null &&
          test.static_water_level_m !== undefined
          ? C.fmtNum(test.static_water_level_m) + ' m' : '—'],
        ['Maximum drawdown', analysis.max_drawdown_m
          ? C.fmtNum(analysis.max_drawdown_m) + ' m' : '—'],
      ];
      if (analysis.transmissivity_m2_per_day) {
        rows.push(['Transmissivity',
          C.fmtNum(analysis.transmissivity_m2_per_day) + ' m2/day']);
      }
      if (rec && rec.specific_capacity_m3hr_per_m) {
        rows.push(['Specific capacity',
          C.fmtNum(rec.specific_capacity_m3hr_per_m) + ' m3/h per m']);
      }
      b.table(rows, { header: ['Item', 'Value'], caption: 'Pumping test summary',
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
      ['Dynamic water level', dwl !== null ? C.fmtNum(dwl) + ' m' : '—'],
      ['Drawdown', (dwl !== null && swl !== null)
        ? C.fmtNum(dwl - swl) + ' m' : '—'],
      ['Flow rate', flow ? C.fmtNum(flow * 1000) + ' L/h' : 'pending'],
      ['Pump type', context.pumpType || 'Handpump'],
      ['Installation depth', rec && rec.pump_installation_depth_m
        ? C.fmtNum(rec.pump_installation_depth_m) + ' m'
        : (test && test.pump_setting_m ? C.fmtNum(test.pump_setting_m) + ' m' : '—')],
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
          caption: 'Parameters above guideline or standard limits',
          fontSize: 9, colWidthsCm: [3.8, 1.8, 1.8, 2.2, 6.0],
        });
      }
      section += 1;
    }

    b.heading(section + '. Recommendations and Conclusions', 1);
    var advice = [];
    if (String(log.status || '').toLowerCase().indexOf('success') === 0 ||
        (rec && rec.safe_yield_m3_per_h)) {
      advice.push('The borehole is successful and sustainable when operated ' +
        'as recommended.');
    }
    if (rec && rec.safe_yield_m3_per_h) {
      advice.push('The recommended abstraction rate is ' +
        C.fmtNum(rec.safe_yield_m3_per_h) + ' m3/h (safety factor ' +
        C.formatG(rec.safety_factor) + ' applied to the long term yield).');
      if (rec.pump_installation_depth_m) {
        advice.push('The pump installation depth is ' +
          C.fmtNum(rec.pump_installation_depth_m) + ' m.');
      }
      advice.push('The pump should rest for at least one hour in every ' +
        'pumping cycle and the pumping water level should be checked routinely.');
    } else if (analysis && test && !test.has_discharge) {
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
    b.references([REFERENCES.rwsn_professional, REFERENCES.rwsn_supervision]);
    b.glossary(GLOSSARY);
    return b;
  }

  /* --- 3. pumping test ------------------------------------------------------- */

  async function pumpingReport(context) {
    var b = new ReportBuilder({ style: context.style, title: 'Pumping Test Report' });
    var analysis = context.analysis, test = analysis.test, site = test.site || {};
    var rec = analysis.yield_recommendation;
    var figures = context.figures || [];

    b.cover(['Pumping Test Report',
      (test.borehole_ref ? test.borehole_ref + ' — ' : '') + (site.community || '')],
      [], siteDetails(site, [
        ['Borehole reference', test.borehole_ref || '—'],
        ['Test type', test.test_type || '—'],
        ['Static water level', test.static_water_level_m !== null
          ? test.static_water_level_m.toFixed(2) + ' m' : '—'],
        ['Borehole depth', test.borehole_depth_m ? C.fmtNum(test.borehole_depth_m) + ' m' : '—'],
      ]));
    b.provisionalStamp(context.readiness);
    b.tableOfContents();

    b.executiveSummary([
      'A ' + (test.test_type || 'pumping') + ' test was carried out on borehole ' +
        (test.borehole_ref || '') + ' at ' + (site.community || 'the site') + '.',
      analysis.transmissivity_m2_per_day
        ? 'The transmissivity of the aquifer is about ' +
          S.sig(analysis.transmissivity_m2_per_day, 3) + ' m²/day. The recommended ' +
          'safe yield is ' + C.yieldRangeText(rec) + ', with the pump set at ' +
          (rec.pump_installation_depth_m !== null
            ? rec.pump_installation_depth_m.toFixed(0) + ' m' : 'a depth to be confirmed') + '.'
        : 'Yield results are pending: ' + (rec.pending_reason || 'inputs are missing') + '.',
    ], [
      analysis.transmissivity_m2_per_day
        ? 'Transmissivity: ' + S.sig(analysis.transmissivity_m2_per_day, 3) + ' m²/day' : null,
      rec.specific_capacity_m3hr_per_m
        ? 'Specific capacity: ' + rec.specific_capacity_m3hr_per_m.toFixed(2) + ' m³/h per m' : null,
      rec.safe_yield_m3_per_h ? 'Safe yield: ' + C.yieldRangeText(rec) : null,
      rec.pump_installation_depth_m !== null
        ? 'Recommended pump setting: ' + rec.pump_installation_depth_m.toFixed(0) + ' m' : null,
    ]);

    b.heading('1. Test Details', 1);
    b.keyValueTable([
      ['Borehole', test.borehole_ref || '—'],
      ['Test type', test.test_type || '—'],
      ['Static water level', test.static_water_level_m !== null
        ? test.static_water_level_m.toFixed(2) + ' m' : '—'],
      ['Pump setting during test', test.pump_setting_m ? C.fmtNum(test.pump_setting_m) + ' m' : '—'],
      ['Pumping duration', test.pumping_duration_min
        ? C.fmtNum(test.pumping_duration_min) + ' min' : '—'],
      ['Step length', test.step_length_min ? C.fmtNum(test.step_length_min) + ' min' : '—'],
    ]);

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
    }
    if (analysis.recovery) {
      b.heading('Theis recovery', 2);
      b.paragraph('Residual drawdown against log(t/t\') gives a transmissivity ' +
        'of ' + S.sig(analysis.recovery.transmissivity_m2_per_day, 3) + ' m²/day ' +
        '(r² = ' + analysis.recovery.r_squared.toFixed(3) + '). Recovery is the ' +
        'least affected by well losses and is the preferred estimate.',
        { align: 'justify' });
    }
    if (analysis.theis) {
      b.heading('Theis type curve', 2);
      b.paragraph('A least squares fit of the Theis well function gives a ' +
        'transmissivity of ' + S.sig(analysis.theis.transmissivity_m2_per_day, 3) +
        ' m²/day with a storativity of ' + S.sig(analysis.theis.storativity, 2) +
        (analysis.theis.storativity_reliable ? '.'
          : '. Storativity is not resolvable from a single pumped well and is ' +
            'reported for completeness only.'), { align: 'justify' });
    }
    if (analysis.step_test) {
      b.heading('Step drawdown analysis', 2);
      b.paragraph('The Hantush-Bierschenk analysis separates aquifer loss from ' +
        'well loss: B = ' + S.sig(analysis.step_test.aquifer_loss_B, 3) +
        ' day/m² and C = ' + S.sig(analysis.step_test.well_loss_C, 3) + ' day²/m⁵.',
        { align: 'justify' });
      b.table(analysis.step_test.steps.map(function (s) {
        return [String(s.step), S.sig(s.discharge_m3_per_h, 3),
          s.drawdown_end_m.toFixed(2), S.sig(s.sw_over_q_day_per_m2, 3),
          s.efficiency_percent.toFixed(0) + '%'];
      }), {
        header: ['Step', 'Q (m³/h)', 'Drawdown (m)', 's/Q (day/m²)', 'Well efficiency'],
        caption: 'Step test results',
      });
    }
    figures.forEach(function (f) { b.figure(f.image, f.caption, f.widthCm || 15); });

    b.heading('4. Results Summary', 1);
    b.table([
      ['Transmissivity (preferred)', analysis.transmissivity_m2_per_day
        ? S.sig(analysis.transmissivity_m2_per_day, 3) + ' m²/day' : 'pending'],
      ['Cooper-Jacob T', analysis.cooper_jacob
        ? S.sig(analysis.cooper_jacob.transmissivity_m2_per_day, 3) + ' m²/day' : '—'],
      ['Recovery T', analysis.recovery
        ? S.sig(analysis.recovery.transmissivity_m2_per_day, 3) + ' m²/day' : '—'],
      ['Theis T', analysis.theis
        ? S.sig(analysis.theis.transmissivity_m2_per_day, 3) + ' m²/day' : '—'],
      ['Maximum drawdown', analysis.max_drawdown_m !== null
        ? analysis.max_drawdown_m.toFixed(2) + ' m' : '—'],
      ['Specific capacity', rec.specific_capacity_m3hr_per_m
        ? rec.specific_capacity_m3hr_per_m.toFixed(2) + ' m³/h per m' : '—'],
    ], { header: ['Quantity', 'Value'], caption: 'Analysis results',
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
        ['Recommended pump setting', rec.pump_installation_depth_m !== null
          ? rec.pump_installation_depth_m.toFixed(0) + ' m' : '—'],
      ], { header: ['Quantity', 'Value'], caption: 'Yield recommendation',
        colWidthsCm: [7.0, 8.6] });
      if (rec.envelope_basis) b.paragraph(rec.envelope_basis, { align: 'justify' });
    } else {
      b.paragraph('The yield recommendation is pending: ' +
        (rec.pending_reason || 'required inputs are missing') + '.', { bold: true });
    }

    var seasonal = context.seasonal;
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
        caption: 'Safe yield and pump setting at each seasonal water level',
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
      if (seasonal.pump_installation_depth_m !== null) {
        b.paragraph('Set the pump intake at ' +
          C.fmtNum(seasonal.pump_installation_depth_m) + ' m below ground ' +
          'level: deep enough for the drought case, because the pump is ' +
          'fitted once and a pump that draws air in a bad year loses the ' +
          'village its borehole in the year it is needed most.', { bold: true });
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
      caption: 'Laboratory results against WHO and national standards',
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
        ], { header: ['Index', 'Value'], caption: 'Corrosivity indices',
          colWidthsCm: [8.0, 7.6] });
      }
      b.paragraph(cor.materials_note, { align: 'justify' });
      if (cor.assumptions && cor.assumptions.length) b.bullets(cor.assumptions);
    }

    b.heading('5. Hydrochemical Facies', 1);
    figures.forEach(function (f) { b.figure(f.image, f.caption, f.widthCm || 14); });

    b.heading('6. Recommendations', 1);
    var recommendations = [];
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
    if (assessment.corrosivity && assessment.corrosivity.is_aggressive) {
      recommendations.push('Specify uPVC or stainless steel rising main and pump ' +
        'components; avoid galvanised iron.');
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
    b.references([REFERENCES.who, REFERENCES.stop_the_rot]);
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
    ], { header: ['Quantity', 'Value'], caption: 'Quantities driving the estimate',
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
      caption: 'Bill of quantities', fontSize: 8.5,
      colWidthsCm: [1.3, 1.9, 5.6, 1.5, 1.5, 1.9, 1.9],
    });

    b.heading('4. Cost Summary', 1);
    b.table([
      ['Direct works cost', S.money(estimate.direct_cost_usd, 0),
        S.thousands(estimate.in_local(estimate.direct_cost_usd), 0)],
      ['Overheads (' + estimate.overheads_percent + '%)',
        S.money(estimate.overheads_usd, 0),
        S.thousands(estimate.in_local(estimate.overheads_usd), 0)],
      ['Total cost', S.money(estimate.total_cost_usd, 0),
        S.thousands(estimate.in_local(estimate.total_cost_usd), 0)],
      ['Cost per metre drilled', S.money(estimate.cost_per_meter_usd, 0),
        S.thousands(estimate.in_local(estimate.cost_per_meter_usd), 0)],
      ['Margin (' + estimate.margin_percent + '%)', S.money(estimate.margin_usd, 0),
        S.thousands(estimate.in_local(estimate.margin_usd), 0)],
      ['Contract price', S.money(estimate.price_usd, 0),
        S.thousands(estimate.in_local(estimate.price_usd), 0)],
      ['Contingency (' + estimate.contingency_percent + '%)',
        S.money(estimate.contingency_usd, 0),
        S.thousands(estimate.in_local(estimate.contingency_usd), 0)],
      ['Planning budget', S.money(estimate.budget_usd, 0),
        S.thousands(estimate.in_local(estimate.budget_usd), 0)],
    ], {
      header: ['Item', 'US$', 'SLE'], caption: 'Cost and price summary',
      colWidthsCm: [7.0, 4.3, 4.3],
    });
    figures.forEach(function (f) { b.figure(f.image, f.caption, f.widthCm || 15); });

    b.heading('5. Notes and Exclusions', 1);
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
      caption: 'Checklist progress by stage', fontSize: 9,
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
        caption: 'Field acceptance checks', fontSize: 8.5,
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

  async function handoverReport(context) {
    var b = new ReportBuilder({ style: context.style, title: 'Project Handover Report' });
    var site = context.site || {}, log = context.log || {}, design = context.design;
    var analysis = context.analysis, assessment = context.assessment;
    var figures = context.figures || [];
    var rec = analysis ? analysis.yield_recommendation : null;

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
          ', which is sufficient for about ' +
          Math.round(rec.safe_yield_m3_per_h * 1000 * 8 / 20) +
          ' people at 20 litres per person per day over an eight hour pumping day.'
        : '',
      assessment ? assessment.verdict : '',
    ], [
      log.total_depth_m ? 'Depth: ' + C.fmtNum(log.total_depth_m) + ' m' : null,
      rec && rec.safe_yield_m3_per_h ? 'Safe yield: ' + C.yieldRangeText(rec) : null,
      rec && rec.pump_installation_depth_m !== null
        ? 'Pump setting: ' + rec.pump_installation_depth_m.toFixed(0) + ' m' : null,
      assessment
        ? 'Water quality: ' + C.VERDICT_LONG[assessment.verdict_state].toLowerCase()
        : null,
    ]);

    b.heading('1. Project Summary', 1);
    b.keyValueTable(siteDetails(site));

    areaSection(b, context, '1.1 Location and setting');

    b.heading('2. Works Completed', 1);
    b.bullets([
      log.total_depth_m ? 'Borehole drilled to ' + C.fmtNum(log.total_depth_m) + ' m.' : null,
      design ? 'Cased and screened with ' + C.fmtNum(design.total_screen_length_m) +
        ' m of screen; gravel packed and grout sealed.' : null,
      'Borehole developed and test pumped.',
      assessment ? 'Water quality sampled and analysed.' : null,
      'Headworks constructed with an apron, drainage channel and soakaway.',
      'Handpump installed and commissioned.',
    ].filter(Boolean).concat(context.worksNotes || []));

    b.heading('3. Borehole Data Sheet', 1);
    var dataRows = [
      ['Borehole reference', log.borehole_ref || context.boreholeRef || '—'],
      ['Total depth', log.total_depth_m ? C.fmtNum(log.total_depth_m) + ' m' : '—'],
      ['Static water level', analysis && analysis.test.static_water_level_m !== null
        ? analysis.test.static_water_level_m.toFixed(2) + ' m' : '—'],
      ['Safe yield', rec ? C.yieldRangeText(rec) : '—'],
      ['Pump setting', rec && rec.pump_installation_depth_m !== null
        ? rec.pump_installation_depth_m.toFixed(0) + ' m' : '—'],
      ['Screened intervals', design ? design.screens.map(function (s) {
        return s.top_m.toFixed(1) + '–' + s.bottom_m.toFixed(1) + ' m'; }).join(', ') : '—'],
      ['Casing', design ? design.casing_diameter_in + '" ' + design.casing_material : '—'],
    ];
    b.table(dataRows, { header: ['Item', 'Value'],
      caption: 'Borehole data sheet', colWidthsCm: [6.0, 9.6] });
    figures.forEach(function (f) { b.figure(f.image, f.caption, f.widthCm || 14); });

    b.heading('4. Water Quality', 1);
    if (assessment) {
      b.paragraph(assessment.verdict, { align: 'justify' });
      if (assessment.corrosivity) {
        b.paragraph(assessment.corrosivity.materials_note, { align: 'justify' });
      }
    } else {
      b.paragraph('No water quality analysis was available at handover. Sample ' +
        'the source and have it analysed before the supply is used for drinking.',
        { align: 'justify' });
    }

    b.heading('5. Operation and Maintenance Guidance', 1);
    b.bullets([
      'Keep the apron, drainage channel and soakaway clean and in good repair; ' +
        'standing water beside the headworks is the commonest route for ' +
        'contamination to reach the borehole.',
      'Keep animals and latrines at least 30 m from the borehole, and never ' +
        'site a new latrine upgradient of it.',
      'Pump gently and steadily. Do not exceed the recommended pump setting ' +
        'depth or the safe yield.',
      'Inspect the rising main and pump rods for corrosion at each service.',
      'Report any change in taste, smell, colour or yield to the district water ' +
        'office immediately.',
      'Keep a record of every repair, with the date, the part replaced and the cost.',
    ].concat(context.omNotes || []));

    b.heading('6. Community / WASH Committee', 1);
    if ((context.committee || []).length) {
      b.table(context.committee.map(function (member) {
        return [member.name || '', member.role || '', member.contact || ''];
      }), { header: ['Name', 'Role', 'Contact'],
        caption: 'Water and sanitation committee', colWidthsCm: [5.5, 5.0, 5.1] });
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
    b.references([REFERENCES.rwsn_professional, REFERENCES.who, REFERENCES.unicef_toolkit]);
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
      header: ['', ''], caption: 'Borehole details', colWidthsCm: [5.0, 10.0] });
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
      b.paragraph(state.undated_events + ' record(s) carry a date that could ' +
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
        caption: 'Everything recorded against this borehole',
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
      caption: 'Work measured to date and what is payable on it',
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
    handoverReport: handoverReport,
    assetPlacard: assetPlacard, assetRecordReport: assetRecordReport,
    paymentCertificate: paymentCertificate,
    REFERENCES: REFERENCES, GLOSSARY: GLOSSARY, statusLabel: statusLabel,
  };
}(typeof window !== 'undefined' ? window : globalThis));

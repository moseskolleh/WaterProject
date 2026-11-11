
  /* ============================================================ export */

  /* The class that marks a map drawn as a sheet of paper, for the page. */
  var SHEET_CLASS = 'sheet-paper';

  /* A figure as it leaves the page, for a report or as a file: without the
   * hover layer, and without what is there for the page alone - the app's
   * face, which a file or a rasterised image cannot load, and the class the
   * stylesheet frames a map by. What goes out is what always went out. */
  function exportCopy(svg) {
    var clone = svg.cloneNode(true);
    Array.prototype.slice.call(clone.querySelectorAll('[data-export="skip"]'))
      .forEach(function (node) { node.parentNode.removeChild(node); });
    if (clone.getAttribute('font-family') === FONT) clone.setAttribute('font-family', EXPORT_FONT);
    if (clone.getAttribute('class') === SHEET_CLASS) clone.removeAttribute('class');
    return clone;
  }

  /* Rasterise an SVG to a PNG data URL for embedding in the .docx reports.
   * Elements marked data-export="skip" (the hover layer) are dropped first. */
  function toPng(svg, options) {
    var opts = options || {};
    var scale = opts.scale || 2;
    var clone = exportCopy(svg);
    var viewBox = (clone.getAttribute('viewBox') || '0 0 720 420').split(/\s+/).map(Number);
    var w = viewBox[2], h = viewBox[3];
    clone.setAttribute('width', w);
    clone.setAttribute('height', h);
    clone.setAttribute('xmlns', NS);
    var source = new XMLSerializer().serializeToString(clone);
    var url = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(source);

    return new Promise(function (resolve, reject) {
      var img = new Image();
      img.onload = function () {
        var canvas = document.createElement('canvas');
        canvas.width = Math.round(w * scale);
        canvas.height = Math.round(h * scale);
        var ctx = canvas.getContext('2d');
        ctx.fillStyle = opts.background || '#FFFFFF';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
        resolve({
          dataUrl: canvas.toDataURL('image/png'),
          width: canvas.width, height: canvas.height,
          widthPx: w, heightPx: h,
        });
      };
      img.onerror = function () { reject(new Error('Could not rasterise the figure.')); };
      img.src = url;
    });
  }

  function download(svg, filename) {
    var clone = exportCopy(svg);
    clone.setAttribute('xmlns', NS);
    S.download(filename, new XMLSerializer().serializeToString(clone),
      'image/svg+xml;charset=utf-8');
  }

  /* A figure block: the SVG, a numbered caption, and the buttons that export
   * it or show the numbers as a table. */
  function figure(svg, caption, options) {
    var opts = options || {};
    if (!svg) return null;
    var actions = el('div.figure-actions', [
      opts.table ? S.button('Table', function () {
        S.modal(caption || 'Figure data', opts.table());
      }, { variant: 'quiet' }) : null,
      S.button('PNG', function () {
        /* the rasteriser can fail - an unloadable font, a tainted canvas -
         * and with no handler the button simply did nothing */
        toPng(svg, { scale: 2 }).then(function (png) {
          return fetch(png.dataUrl).then(function (r) { return r.blob(); })
            .then(function (blob) {
              S.download((opts.filename || S.slug(caption || 'figure')) + '.png', blob);
            });
        }).catch(function (e) {
          S.toast('Could not export this figure as a PNG: ' + e.message, 'error');
        });
      }, { variant: 'quiet' }),
      S.button('SVG', function () {
        download(svg, (opts.filename || S.slug(caption || 'figure')) + '.svg');
      }, { variant: 'quiet' }),
    ]);
    return el('figure.figure', [
      svg,
      caption ? el('figcaption', [
        opts.number ? el('span.fig-no', 'Figure ' + opts.number) : null,
        el('span', caption),
        actions,
      ]) : el('figcaption', actions),
    ]);
  }

  GWT.charts = {
    palette: palette, mapPalette: paperPalette, frame: frame, marker: marker, legend: legend,
    polyline: polyline, padDomain: padDomain, freeCorner: freeCorner, linTicks: linTicks, logTicks: logTicks,
    vesCurve: vesCurve, layeredModel: layeredModel,
    /* The survey's own figures. Each takes what gwt-core.js mirrored out of
     * the Python and returns null where the Python refused to draw, so the
     * report prints the engine's reason instead of an empty frame. */
    geoelectricSection: geoelectricSection,
    modelPseudosection: modelPseudosection,
    apparentPseudosection: apparentPseudosection,
    subsurfaceMap: subsurfaceMap, subsurfaceMaps: subsurfaceMaps,
    suitabilityMap: suitabilityMap, groundProfile: groundProfile,
    /* The terrain analysis's four figures (PLAN.md step 4.1), each drawn
     * from C.terrainDisplayLayers, and the raster they are painted with. */
    terrainRelief: terrainRelief, wetnessMap: wetnessMap, curvatureMaps: curvatureMaps,
    hillshadeDirections: hillshadeDirections, rasterImage: rasterImage,
    /* and the lineament candidates' two (PLAN.md step 4.2), and the survey
     * plan laid across them (step 4.3) */
    lineamentMap: lineamentMap, lineamentRose: lineamentRose, surveyPlanMap: surveyPlanMap,
    rampColour: rampColour, colourRamps: COLOUR_RAMPS, colourBar: colourBar,
    testOverview: testOverview, cooperJacob: cooperJacob,
    recovery: recoveryPlot, stepTest: stepTestPlot, diagnostic: diagnosticPlot,
    piper: piper, stiff: stiff, boreholeDesign: boreholeDesign,
    lithologyColour: lithologyColour,
    depthSpine: depthSpine, guidelineSpine: guidelineSpine,
    costBreakdown: costBreakdown, programmeGantt: programmeGantt,
    costDistribution: costDistribution,
    /* the calibration report's two (PLAN.md step 5.2) */
    depthCalibration: depthCalibration, reliabilityDiagram: reliabilityDiagram,
    /* the time to the first failure (PLAN.md step 7.4) */
    survivalCurves: survivalCurves,
    choropleth: choropleth, siteMap: siteMap, thematicMap: thematicMap,
    studyAreaMap: studyAreaMap, studyAreaRadiusKm: studyAreaRadiusKm,
    chiefdomLabel: chiefdomLabel, relativeLuminance: relativeLuminance,
    geologyColours: GEOLOGY_COLOURS, mapTones: {
      sea: MAP_SEA, land: MAP_LAND, foreignLand: MAP_FOREIGN_LAND,
      notMapped: MAP_NOT_MAPPED, noData: MAP_NO_DATA,
    },
    /* the caller says which sheet the layer came off; both bundled layers
     * are 1:5,000,000, and the aquifer map carries its publisher's own
     * limit on it as well */
    usePrintPalette: usePrintPalette,
    scaleCaveat: scaleCaveat, usgsSourceScale: USGS_SOURCE_SCALE,
    bgsSourceScale: BGS_SOURCE_SCALE, bgsPublisherNote: BGS_PUBLISHER_NOTE,
    mapProjection: mapProjection, projectionInto: projectionInto,
    geometryPath: geometryPath, quantileBreaks: quantileBreaks,
    pointInFeature: pointInFeature, ringInBox: ringInBox,
    declutter: declutter, graticuleStep: graticuleStep,
    textWidth: textWidth, wrapText: wrapText, ellipsise: ellipsise,
    stackLabels: stackLabels,
    toPng: toPng, downloadSvg: download, figure: figure,
  };
}(typeof window !== 'undefined' ? window : globalThis));

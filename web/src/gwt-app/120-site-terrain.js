
  /* --- topography and terrain (PLAN.md step 4.1) ---------------------------
   *
   * No elevation model is bundled with the app and none is downloaded, so
   * the terrain is worked out from tiles the operator drops on the card. They
   * are not kept with the sources a sheet is: a File costs nothing until it
   * is read, and it is read only in the parts asked for - its directories
   * when it is added, and the blocks the window meets when the terrain is
   * analysed. Nothing of it is saved with the project, and another project,
   * opened or started, or the workspace reset, drops it all (forgetTerrain).
   */
  function blankTerrainSession() {
    return {
      /* the files, in the order they were added */
      files: [],
      /* File -> {found, refusal}: what elevationFile opened, or why it
       * refused the file; a file still being opened has no entry */
      opened: new Map(),
      declared: 'detect', declaredText: '',
      /* null until the operator sets them: the configuration's default */
      radiusKm: null, areaKm2: null,
      /* counts the runs asked for, so that an answer to an older one, or to
       * files since replaced, is dropped */
      run: 0,
      /* a run is reading the files or analysing them, and whether it is
       * still reading the blocks out of the files on the page */
      running: false, reading: false,
      /* what the engine read of the window, and why the last run was refused */
      read: null, refusal: '',
      /* what the page keeps of the analysis of the read (terrainResult),
       * and the figures drawn from it, by name: relief, wetness, curvature
       * and directions; a figure set to null is drawn again, and all four
       * are when the page's colours are no longer those they were drawn
       * in (figuresIn) */
      result: null, figures: null, figuresIn: '',
    };
  }
  var terrainSession = blankTerrainSession();

  /* Another project replaces this one, or the workspace is reset: the
   * tiles, the settings chosen on the card and all made of them belong to
   * the outgoing site, and are dropped as the Python app drops its dem_
   * and terrain_ keys when a project is loaded. A run still going is
   * stopped, and its answer finds a new session and is not shown. */
  function forgetTerrain() {
    dropTerrainRead(terrainSession);
    terrainSession = blankTerrainSession();
  }

  /* What the operator can say the files are, as the Python app offers it. */
  var TERRAIN_SOURCES = [
    { value: 'detect', label: 'Detect from the file names' },
    { value: 'copernicus_glo30', label: 'Copernicus GLO-30' },
    { value: 'srtm', label: 'SRTM' },
    { value: 'other', label: 'Another source' },
  ];

  /* What a file was recognised as, from its name and georeferencing
   * together, in the file list. */
  var TERRAIN_DETECTED = {
    copernicus_glo30: 'recognised as Copernicus GLO-30',
    srtm: 'recognised as SRTM',
    hgt: 'SRTM format, source not stated',
    unidentified: 'source not recognised',
  };

  /* A GeoTIFF is opened as geotiff.open_geotiff opens one: its first 64 KiB,
   * which hold every directory of a cloud-optimised file, then each range
   * still missing rounded up to 64 KiB, for at most 16 more rounds. */
  var TERRAIN_READ_UNIT = 65536;
  var TERRAIN_ROUNDS = 16;

  async function fileBytes(file, offset, length) {
    return new Uint8Array(await file.slice(offset, offset + length).arrayBuffer());
  }

  /* One file opened for its layout alone (C.elevationFile): an .hgt from its
   * name and length, with nothing read, a GeoTIFF from its directories.
   * Refused, it throws the engine's sentence. */
  async function openElevationFile(file) {
    var name = file.name, size = file.size;
    var chunks = [];
    var found = C.elevationFile(name, size, chunks);
    for (var round = 0; Array.isArray(found) && round <= TERRAIN_ROUNDS; round++) {
      for (var k = 0; k < found.length; k++) {
        var offset = found[k][0];
        var length = Math.ceil(found[k][1] / TERRAIN_READ_UNIT) * TERRAIN_READ_UNIT;
        chunks.push([offset, await fileBytes(file, offset, Math.min(length, size - offset))]);
      }
      found = C.elevationFile(name, size, chunks);
    }
    if (Array.isArray(found)) {
      throw new Error(C.phrase('terrain.ends_early', { file: name, part: 'image directory' }));
    }
    return found;
  }

  /* What the operator declared, as the engine takes it: their own words
   * count only for another source. */
  function terrainDeclared(session) {
    return [session.declared, session.declared === 'other' ? session.declaredText : ''];
  }

  /* The engine tasks a terrain run asks for. */
  var TERRAIN_TASKS = ['readElevation', 'analyseTerrain'];

  /* The read, and whatever was made of it, no longer describe the files or
   * their source: they are dropped, and a run still going is stopped, so
   * that the worker is not kept busy on an answer nobody will see, and its
   * bar goes with it. Bumping the run is what drops that answer if it
   * arrives all the same: the engine cannot stop the page's own reads of
   * the files. */
  function dropTerrainRead(session) {
    session.run += 1;
    if (session.running) {
      engine.cancel(TERRAIN_TASKS);
      if (work.terrain) workEnd(work.terrain);
    }
    session.running = false;
    session.reading = false;
    session.read = null;
    session.refusal = '';
    session.result = null;
    session.figures = null;
  }

  /* Files dropped or picked join the list, a file under a name already
   * listed taking its place, and each is opened at once, so a refusal or a
   * question about its source shows beside its name before anything is
   * analysed. */
  async function addTerrainFiles(files) {
    if (!files || !files.length) return;
    var session = terrainSession;
    files.forEach(function (file) {
      session.files = session.files.filter(function (f) { return f.name !== file.name; })
        .concat([file]);
    });
    dropTerrainRead(session);
    render();
    for (var i = 0; i < files.length; i++) {
      var file = files[i], opened;
      try {
        opened = { found: await openElevationFile(file), refusal: '' };
      } catch (e) {
        opened = { found: null, refusal: e.message };
      }
      if (terrainSession === session && session.files.indexOf(file) >= 0) {
        session.opened.set(file, opened);
      }
    }
    refresh();
  }

  function removeTerrainFile(file) {
    var session = terrainSession;
    session.files = session.files.filter(function (f) { return f !== file; });
    session.opened.delete(file);
    dropTerrainRead(session);
    render();
  }

  /* The bytes of each block the plan names, read as C.elevationBlockRanges
   * says, which is how the Python app reads them: file by file, blocks
   * within 64 KiB of each other in one read of at most 16 MiB, the edge
   * blocks of a missing tile included. Each block is cut out with slice,
   * never subarray, so that it holds a buffer of its own: the request to the
   * worker is a copy, and a view would carry the whole read with it.
   * `heard(fraction)` is told how many of the reads are done. Once
   * `current()` says the run is no longer wanted, no further read is
   * started, and the answer is null. */
  async function terrainBlocks(plan, session, heard, current) {
    var fileOf = new Map();
    session.files.forEach(function (file) {
      fileOf.set(session.opened.get(file).found, file);
    });
    var blocks = plan.blocks.map(function () { return null; });
    var reads = C.elevationBlockRanges(plan);
    for (var r = 0; r < reads.length; r++) {
      if (!current()) return null;
      var read = reads[r], bytes;
      try {
        bytes = await fileBytes(fileOf.get(plan.files[read.file]), read.offset, read.length);
      } catch (e) {
        throw new Error('Could not read ' + read.name + ': ' + e.message);
      }
      read.blocks.forEach(function (b) {
        var at = plan.blocks[b].offset - read.offset;
        blocks[b] = bytes.slice(at, at + plan.blocks[b].length);
      });
      heard((r + 1) / reads.length);
    }
    return blocks;
  }

  function terrainRadius(session) {
    return session.radiusKm !== null ? session.radiusKm
      : config().terrain.analysis_radius_km;
  }

  function terrainArea(session) {
    return session.areaKm2 !== null ? session.areaKm2
      : config().terrain.drainage_area_km2;
  }

  /* A device that says it has 2 GB of memory or less is asked before a
   * window of more than a million cells is analysed, since the worker
   * holds the whole window several times over while it works, and a phone
   * short of memory may answer by closing the tab. Only Chromium browsers
   * say how much memory a device has (navigator.deviceMemory, rounded);
   * the others are never asked. */
  var TERRAIN_LOW_MEMORY_GB = 2;
  var TERRAIN_ASK_CELLS = 1000000;

  function terrainNeedsAsking(plan) {
    /* deviceMemory is not in the DOM library tsc checks this file against */
    var memory = /** @type {any} */ (navigator).deviceMemory;
    return memory !== undefined && memory <= TERRAIN_LOW_MEMORY_GB && plan.cells > TERRAIN_ASK_CELLS;
  }

  /* The question, in the browser's own words: the Python app runs on a
   * computer, and never asks it. */
  function askTerrainMemory() {
    var asked = S.modal('This device may run short of memory', el('p',
      'This device reports 2 GB of memory or less; a window this size may close the tab. ' +
      'Run it anyway?'), [
      button('Run it anyway', function () {
        asked.close();
        runTerrain(true);
      }, { variant: 'primary' }),
    ]);
  }

  /* "Analyse the terrain". The window is planned around the site on the
   * page, which is quick: its centre, the square shown and the margin
   * beyond it, the cap, and the blocks each file must give up. Those blocks
   * are read here and handed to the engine worker, which turns them into
   * the window's grid and the read report, and then analyses the grid. The
   * work bar names each stage as the engine does, and its Cancel stops the
   * run (cancelWork). The lines are traced at the card's threshold, as the
   * Python app traces them; one changed while the run was going is traced
   * again from its answer (retraceTerrain). `asked` is true once a device
   * short of memory has been told to go ahead with a large window. */
  async function runTerrain(asked) {
    var session = terrainSession;
    var cfg = config();
    cfg.terrain.drainage_area_km2 = terrainArea(session);
    var latlon = siteLatLon();
    var plan = null, refusal = '';
    try {
      var files = session.files.map(function (file) { return session.opened.get(file).found; });
      var centre = C.windowCentre(store.get('site'), latlon, files);
      plan = C.planElevationWindow(files, centre, terrainRadius(session), cfg, null,
        terrainDeclared(session));
    } catch (e) {
      refusal = e.message;
    }
    /* asked first, with what is on the card left as it is */
    if (plan && !asked && terrainNeedsAsking(plan)) {
      askTerrainMemory();
      return;
    }
    var run = ++session.run;
    function current() { return terrainSession === session && session.run === run; }
    session.read = null;
    session.refusal = refusal;
    session.result = null;
    session.figures = null;
    if (!plan) {
      render();
      return;
    }
    session.running = true;
    var stageRead = C.phrase('terrain.stage_read');
    var job = workBegin('terrain', 'Analysing the terrain');
    workProgress(job, 0, stageRead);
    /* a part of the run, from `from` to `from + width` of the bar: reading
     * the files, reading the window out of their blocks, analysing it */
    function heard(from, width) {
      return function (fraction, label) {
        workProgress(job, from + width * fraction, label || stageRead);
      };
    }
    render();
    try {
      session.reading = true;
      var blocks = await terrainBlocks(plan, session, heard(0, 0.05), current);
      if (!current()) return;
      session.reading = false;
      var read = await engine.readElevation(plan, blocks, cfg, { onProgress: heard(0.05, 0.05) });
      if (!current()) return;
      session.read = read;
      refresh();
      /* The grid is sent once, as itself. The read goes with it for the
       * captions, which take its surface note and its plan, so it goes
       * without the grid and the other layers of a value a cell. */
      var answer = await engine.analyseTerrain(read.grid, cfg,
        Object.assign({}, read, { grid: null, assumedSea: null, reasons: null }), read.centre.label,
        { onProgress: heard(0.1, 0.9) });
      if (!current()) return;
      session.result = terrainResult(read, answer, cfg, latlon);
      retraceTerrain(session);
    } catch (e) {
      if (!current() || engine.isCancelled(e)) return;
      /* a refusal is the engine's sentence; a worker that stopped says
       * so in its own */
      session.refusal = e.message;
    } finally {
      /* Of the read, the page keeps what the card, the captions and the
       * GeoJSON take from it: its notes and plan, its credits, and the
       * grid's axes, label and source. Its layers of a value a cell (the
       * heights, the assumed sea and the reasons) went to the engine with
       * the request, and nothing on the page reads them once it has
       * answered. */
      if (read) {
        read.grid.z = null;
        read.grid.assumedSea = null;
        read.assumedSea = null;
        read.reasons = null;
      }
      workEnd(job);
      if (current()) {
        session.running = false;
        session.reading = false;
      }
      refresh();
    }
  }

  /* What the page keeps of an analysis: the worker's answer (the display
   * layers, the core at full size, the lines, the summary and the
   * captions, and the lineament candidates with theirs), the settings it
   * was worked out with and the threshold its lines were traced at, the sea
   * cells of the analysed window (assumed sea included; class 2), which the
   * GeoJSON's description reads, and the two GeoJSON files. The figures
   * star the site the window was centred on where it has a GPS fix, named
   * by its community or "Site", as the Python figures mark it
   * (regional._mark_site). */
  function terrainResult(read, answer, cfg, latlon) {
    var cls = answer.core.cls, sea = 0;
    for (var i = 0; i < cls.length; i++) if (cls[i] === 2) sea += 1;
    var result = Object.assign({}, answer, { cfg: cfg, areaKm2: cfg.terrain.drainage_area_km2,
      seaCells: sea, site: latlon ? { lon: latlon.lon, lat: latlon.lat,
        label: store.get('site.community') || 'Site' } : null });
    result.geojson = terrainGeoJson(read, result);
    result.lineamentGeojson = C.lineamentGeoJson(result.lineaments, read.grid.lons, read.grid.lats, {
      label: read.grid.label, figure_credit: read.figureCredit, notice: read.notice, surface: read.surface,
      radius: read.plan.radiusKm, centre: read.centre,
    });
    terrainPlan(read, result);
    return result;
  }

  /* The survey plan (PLAN.md step 4.3), laid across the candidates within
   * the service radius of the site, as the Python app lays it in the same
   * press: it needs the site's GPS fix, and keeps clear of the water points
   * the page holds now, which it keeps with it (planWaterPoints). Its
   * captions, or why there is no plan, and its GPX and GeoJSON, written
   * only where it lays a line. A new threshold lays it again
   * (retraceTerrain), as a press in the Python app does. */
  function terrainPlan(read, result) {
    var cfg = result.cfg;
    result.planWaterPoints = (derived || {}).waterPoints || null;
    /* and how far round the site they were looked up, so that a lookup
     * short of a water point's reach says so rather than leaving a peg in
     * a ring it never loaded */
    result.planSearchedM = result.site ? waterPointsSearched(result.site) : null;
    result.plan = result.site ? C.surveyPlan(result.lineaments, result.core, result.parts,
      [result.site.lon, result.site.lat], result.planWaterPoints, cfg.terrain, cfg.ves, undefined,
      result.planSearchedM) : null;
    result.planCaptions = C.surveyPlanCaptions(result.plan, read.centre.label);
    var laid = !!result.plan && result.plan.basis !== 'none';
    var told = { where: read.centre.label, label: read.grid.label, site_label: store.get('site.community') || 'Site' };
    result.planGpx = laid ? C.surveyPlanGpx(result.plan, result.core.lons, result.core.lats, told) : null;
    result.planGeoJson = laid ? C.surveyPlanGeoJson(result.plan, result.core.lons, result.core.lats, told) : null;
    /* what the desk study says of it (PLAN.md step 4.4), from the captions
     * merged as the Python app merges them */
    result.desk = C.deskStudyTerrain(result.lineaments, result.plan, result.core.lons, result.core.lats,
      Object.assign({}, result.captions, result.lineamentCaptions, result.planCaptions), read.grid.label);
  }

  /* The drainage lines shown, as GeoJSON, told what terrain.geojson_meta
   * tells it in the Python app, so that its description says what the
   * captions say. */
  function terrainGeoJson(read, result) {
    var settings = result.cfg.terrain;
    return C.drainageGeoJson(result.core, result.parts, {
      label: read.grid.label, figure_credit: read.figureCredit, notice: read.notice,
      surface: read.surface, area: settings.drainage_area_km2, radius: read.plan.radiusKm,
      margin: read.plan.marginKm, centre: read.centre, fill_note_m: settings.fill_note_m,
      sea_clean: read.grid.seaClean, sea_cells: result.seaCells, sea_level_m: settings.sea_level_m,
    });
  }

  /* A new drainage threshold for the analysis on show, worked out on the
   * page from the core the worker handed over, without analysing the
   * ground again. The lines are traced afresh by C.drainageLinks, the one
   * function both apps trace with, on the same core, so they are the
   * lines an analysis at this threshold draws in either app. What names
   * the threshold follows them: the summary's counts of line cells
   * (C.streamCounts, which the analysis counts them with), which the
   * relief's caption gives a share of, the captions (C.terrainCaptions,
   * given the parts of an analysis it reads) and the GeoJSON. Nothing else
   * depends on the threshold but the survey plan, which keeps clear of the
   * lines, so of the figures only the relief and the plan are drawn again. */
  function retraceTerrain(session) {
    var result = session.result, read = session.read, area = terrainArea(session);
    if (!result || !read || result.areaKm2 === area) return;
    var cfg = Object.assign({}, result.cfg, {
      terrain: Object.assign({}, result.cfg.terrain, { drainage_area_km2: area }) });
    var lines = C.drainageLinks(result.core, area);
    var summary = Object.assign({}, result.summary, C.streamCounts(result.core, area));
    var captions = C.terrainCaptions({ grid: read.grid, core: result.core, settings: cfg.terrain,
      summary: summary, kCells: result.kCells }, read, read.centre.label);
    var next = Object.assign({}, result, { cfg: cfg, areaKm2: area, links: lines.links,
      parts: lines.parts, summary: summary, captions: captions });
    next.geojson = terrainGeoJson(read, next);
    terrainPlan(read, next);
    session.result = next;
    if (session.figures) {
      session.figures.relief = null;
      session.figures.plan = null;
    }
  }

  function sizeText(bytes) {
    return bytes >= 1e9 ? (bytes / 1e9).toFixed(1) + ' GB'
      : bytes >= 1e6 ? (bytes / 1e6).toFixed(1) + ' MB'
        : (bytes / 1e3).toFixed(1) + ' kB';
  }

  /* The drop zone, its handlers as uploadZone has them. Any file can be
   * picked: an accept list makes Android's picker grey out .hgt, and each
   * file is read to see what it is. */
  function terrainDropZone() {
    var zone = el('div.upload-zone', {
      tabindex: '0', role: 'button',
      onclick: function () { pick(); },
      onkeydown: function (e) {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(); }
      },
    }, [
      el('strong', 'Elevation model tiles'),
      el('span', 'Click or drop GeoTIFF (.tif) or SRTM-format (.hgt) tiles here'),
    ]);
    function pick() { S.pickFile('', true).then(addTerrainFiles); }
    zone.addEventListener('dragover', function (e) {
      e.preventDefault(); zone.classList.add('over');
    });
    zone.addEventListener('dragleave', function () { zone.classList.remove('over'); });
    zone.addEventListener('drop', function (e) {
      e.preventDefault(); zone.classList.remove('over');
      addTerrainFiles(Array.prototype.slice.call(e.dataTransfer.files || []));
    });
    return zone;
  }

  /* A file in the list: its size and the source it was recognised as, or
   * why it was refused, and what is said about it alone, in the engine's
   * words under the source declared now. */
  function terrainFileNode(session, file) {
    var opened = session.opened.get(file);
    var details = [sizeText(file.size)];
    if (!opened) details.push('opening…');
    else if (opened.found) details.push(TERRAIN_DETECTED[opened.found.sourceId]);
    return el('div.terrain-file', { 'data-file': file.name }, [
      el('div.btn-row', [
        el('strong', file.name),
        el('span.muted', details.join(' · ')),
        button('Remove', function () { removeTerrainFile(file); }, { variant: 'ghost' }),
      ]),
      opened && opened.refusal
        ? el('div.callout.callout-bad', el('p', opened.refusal)) : null,
      opened && opened.found
        ? C.fileNotes(opened.found, terrainDeclared(session)).map(function (note) {
          return el('div.callout.callout-warn', el('p', note));
        }) : null,
    ]);
  }

  /* What the read found, sentence by sentence, as both apps say it under
   * the file list. */
  function terrainReadNodes(read) {
    return el('div.terrain-read.wrap-anywhere',
      read.notes.map(function (note) { return el('p', note); }));
  }

  /* The four figures, by the name the captions give each, which also
   * names its files as the Python app saves them (terrain_<name>.png and
   * .svg), and the builder in gwt-charts.js that draws it; then the
   * lineament candidates' two (PLAN.md step 4.2), named by their own
   * captions and drawn the same way, the rose only where there is a
   * candidate. */
  var TERRAIN_FIGURES = [
    ['relief', 'terrainRelief'], ['wetness', 'wetnessMap'], ['curvature', 'curvatureMaps'],
    ['directions', 'hillshadeDirections'],
  ];
  var LINEAMENT_FIGURES = [['lineaments', 'lineamentMap'], ['rose', 'lineamentRose']];

  /* The figures of the analysis on show, each with the engine's captions
   * under it and its PNG and SVG buttons; the survey plan's figure and its
   * soundings where it lays a line, or why there is none; and the drainage
   * lines and the lineament candidates as GeoJSON and the plan as GPX and a
   * GeoLibre project, as the Python app writes them. A figure is drawn once
   * and kept: the four from a display of 1024 cells a side take most of a
   * second, and the page is drawn again at every change on it. One set to
   * null (a new threshold sets the relief's and the plan's) is drawn again,
   * and all of them are when the theme has changed the colours they were
   * drawn in, which are the page's (charts.palette). */
  function terrainFigureNodes(session) {
    var result = session.result;
    var colours = JSON.stringify(charts.palette());
    if (!session.figures || session.figuresIn !== colours) {
      session.figures = { relief: null, wetness: null, curvature: null, directions: null, lineaments: null,
        rose: null, plan: null };
      session.figuresIn = colours;
    }
    var figures = session.figures;
    var opts = { parts: result.parts, summary: result.summary, captions: result.captions,
      site: result.site, figureCredit: session.read.figureCredit, cfg: result.cfg.terrain };
    var lineamentOpts = Object.assign({}, opts, {
      captions: Object.assign({}, result.captions, result.lineamentCaptions), lineaments: result.lineaments,
      axes: { lons: session.read.grid.lons, lats: session.read.grid.lats } });
    var lineamentFigures = result.lineaments.lineaments.length ? LINEAMENT_FIGURES : LINEAMENT_FIGURES.slice(0, 1);
    var laid = !!result.planGpx;
    if (laid && !figures.plan) {
      figures.plan = charts.surveyPlanMap(result.display, Object.assign({}, lineamentOpts, {
        captions: Object.assign({}, lineamentOpts.captions, result.planCaptions), plan: result.plan }));
    }
    return [
      TERRAIN_FIGURES.map(function (entry) {
        var name = entry[0];
        if (!figures[name]) figures[name] = charts[entry[1]](result.display, opts);
        return charts.figure(figures[name], result.captions[name], { filename: 'terrain_' + name });
      }),
      lineamentFigures.map(function (entry) {
        var name = entry[0];
        if (!figures[name]) {
          figures[name] = charts[entry[1]](name === 'rose' ? result.lineaments : result.display, lineamentOpts);
        }
        return charts.figure(figures[name], result.lineamentCaptions[name], { filename: 'terrain_' + name });
      }),
      laid ? charts.figure(figures.plan, result.planCaptions.plan, { filename: 'terrain_plan' })
        : el('p.muted', { 'data-plan': 'none' }, result.planCaptions.plan),
      laid && result.plan.soundings.length ? terrainPlanTable(result) : null,
      el('div.btn-row', [
        button('Drainage lines (GeoJSON)', function () {
          S.download('drainage_lines.geojson', result.geojson, 'application/geo+json');
        }, { variant: 'ghost' }),
        button('Lineament candidates (GeoJSON)', function () {
          S.download('lineament_candidates.geojson', result.lineamentGeojson, 'application/geo+json');
        }, { variant: 'ghost' }),
        laid ? button('Survey plan (GPX)', function () {
          S.download('survey_plan.gpx', result.planGpx, 'application/gpx+xml');
        }, { variant: 'ghost' }) : null,
        laid ? button('Survey plan (GeoLibre)', function () {
          GWT.geolibre.saveSurveyPlan({ planGeoJson: result.planGeoJson, lineamentGeoJson: result.lineamentGeojson,
            waterPoints: result.planWaterPoints, site: { lat: result.site.lat, lon: result.site.lon,
              label: store.get('site.community') || '' } });
        }, { variant: 'ghost' }) : null,
      ]),
    ];
  }

  /* The proposed soundings as both apps list them under the plan: each
   * one's name, line, distance along it, position and what is said of it
   * (C.surveySoundingText). */
  function terrainPlanTable(result) {
    var plan = result.plan;
    return S.table([
      { key: 'name', label: 'Sounding' }, { key: 'line', label: 'Line', align: 'right' },
      { key: 'at', label: 'Along the line (m)', align: 'right' },
      { key: 'lat', label: 'Latitude', align: 'right' }, { key: 'lon', label: 'Longitude', align: 'right' },
      { key: 'text', label: 'Where and how' },
    ], plan.soundings.map(function (x) {
      var p = C.lineamentLonLat(plan, result.core.lons, result.core.lats, x.point);
      return { name: C.phrase('survey_plan.ves_name', { n: x.id }), line: x.line, at: C.pyFixed(x.at_m, 1),
        lat: C.pyFixed(p[1], 6), lon: C.pyFixed(p[0], 6), text: C.surveySoundingText(plan, x) };
    }));
  }

  /* The Copernicus licence's liability sentence, in small print where the
   * files hold a Copernicus tile: under the downloads once there are
   * figures, as the Python app prints it, and under the read report until
   * then. */
  function terrainNotice(read) {
    return read.notice ? el('p.muted.terrain-notice', el('small', read.notice)) : null;
  }

  function terrainCard() {
    var session = terrainSession;
    var waiting = session.files.some(function (file) { return !session.opened.has(file); });
    var refused = session.files.some(function (file) {
      var opened = session.opened.get(file);
      return !!opened && !!opened.refusal;
    });
    return itemNode('terrain', card('Topography and terrain', [
      el('p.muted', 'No elevation model is bundled with this app and none is ' +
        'downloaded, so the terrain is worked out from tiles you supply: ' +
        'GeoTIFF tiles (.tif) in longitude and latitude, as Copernicus GLO-30 ' +
        'and USGS EarthExplorer SRTM tiles are published and as QGIS saves a ' +
        'clip, and SRTM-format tiles (.hgt), several tiles joined into one ' +
        'model. Keep the names the tiles came with: an .hgt tile is placed by ' +
        'its name alone. Copernicus GLO-30 tiles can be downloaded by hand ' +
        'from the copernicus-dem-30m bucket of the Registry of Open Data on ' +
        'AWS, and NASA SRTM and NASADEM tiles from NASA Earthdata or USGS ' +
        'EarthExplorer. The tiles on viewfinderpanoramas are void-filled ' +
        'compilations of several sources: declare them as Another source. ' +
        'The files are read in this browser, only the parts the window ' +
        'needs, and nothing is uploaded.'),
      /* the terrain work the Python app alone does, and that neither app's
       * reports carry it yet, said before any file is added, as the
       * Python app's Topography tab says it above its uploader */
      el('div.callout.callout-info.terrain-scope', [
        el('p', C.phrase('terrain.python_only')),
        el('p', C.phrase('terrain.not_in_reports')),
      ]),
      terrainDropZone(),
      /* a tile's name is one long word, which a phone has to break, in the
       * list and in the sentences that name it */
      session.files.length ? el('div.terrain-files.wrap-anywhere.mt-s.mb-m',
        session.files.map(function (file) { return terrainFileNode(session, file); })) : null,
      el('div.field-row', [
        field('Source of the elevation model', S.selectInput(session.declared, TERRAIN_SOURCES,
          function (value) {
            session.declared = value;
            dropTerrainRead(session);
            render();
          }), 'Detected, a tile is credited as Copernicus GLO-30 or SRTM only when ' +
          'its name and its georeferencing agree; a source stated here wins.'),
        session.declared === 'other' ? field('The source, in your own words',
          S.textInput(session.declaredText, function (value) {
            session.declaredText = value;
            dropTerrainRead(session);
            render();
          }), 'Named in the figures\' credit line as you write it.') : null,
      ]),
      el('div.field-row', [
        field('Radius of the square shown (km)', S.numberInput(terrainRadius(session),
          function (value) {
            session.radiusKm = value === null ? null : S.clamp(value, 1, 50);
            render();
          }, { min: 1, max: 50, step: 1 })),
        field('Drainage threshold (km²)', S.numberInput(terrainArea(session),
          function (value) {
            session.areaKm2 = value === null ? null : S.clamp(value, 0.05, 100);
            retraceTerrain(session);
            render();
          }, { min: 0.05, max: 100, step: 0.05 }),
        'A drainage line starts where more than this drains to a cell. A new threshold ' +
          'redraws the lines without analysing the ground again.'),
      ]),
      el('div.btn-row.mb-m', [
        button('Analyse the terrain', function () { runTerrain(false); }, {
          variant: 'primary',
          disabled: !session.files.length || waiting || refused || session.running,
        }),
      ]),
      session.running ? el('p.muted', 'Analysing the terrain. The bar at the top of the page ' +
        'shows how far it has got, and its Cancel stops it.') : null,
      /* Opened from file://, the page does the work itself and draws
       * nothing while the engine reads or analyses, so it says so before a
       * run is started; a press of Cancel is read only between the two. In
       * the browser's own words: the Python app always has its engine. */
      !session.running && engine.mode() === 'page'
        ? el('p.muted.terrain-page-only', 'This copy of the app has no background worker (' +
          engine.unavailable() + '), so the analysis will hold the page until it finishes.') : null,
      session.refusal ? el('div.callout.callout-bad.wrap-anywhere',
        el('p', session.refusal)) : null,
      session.read ? terrainReadNodes(session.read) : null,
      session.result ? terrainFigureNodes(session) : null,
      session.read ? terrainNotice(session.read) : null,
    ]));
  }
